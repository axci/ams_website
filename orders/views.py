import logging
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.models import DeliveryAddress
from catalog.models import Product
from catalog.pricing import price_type_for_user
from warehouses.availability import (
    annotate_availability,
    available_map,
    own_warehouse_ids,
)
from warehouses.models import Stock
from warehouses.selection import get_current_warehouse

from .emails import send_order_cancellation, send_order_emails
from .forms import CheckoutForm
from .invoices import build_invoice_xlsx
from .models import CartItem, Favorite, Order, OrderItem
from .utils import get_or_create_cart

logger = logging.getLogger(__name__)


@login_required
def cart_detail(request):
    cart = get_or_create_cart(request.user)
    warehouse = get_current_warehouse(request)
    items = list(cart.items.select_related("product", "product__brand"))
    # Availability = total stock across all warehouses (own + 7-day delivery).
    stock_map = available_map([i.product_id for i in items])
    for item in items:
        item.available = stock_map.get(item.product_id, 0)
    return render(
        request,
        "orders/cart.html",
        {"cart": cart, "items": items, "warehouse": warehouse},
    )


@login_required
@require_POST
def add_to_cart(request, product_id):
    product = get_object_or_404(Product, pk=product_id, is_active=True)
    try:
        quantity = int(request.POST.get("quantity", 1))
    except (TypeError, ValueError):
        quantity = 1
    quantity = max(1, quantity)

    cart = get_or_create_cart(request.user)
    item, created = CartItem.objects.get_or_create(
        cart=cart, product=product, defaults={"quantity": quantity}
    )
    if not created:
        item.quantity += quantity
        item.save(update_fields=["quantity"])
    messages.success(request, f"{product.name} добавлен в корзину.")
    return redirect(request.POST.get("next") or "catalog:product_list")


@login_required
@require_POST
def update_cart_item(request, item_id):
    cart = get_or_create_cart(request.user)
    item = get_object_or_404(CartItem, pk=item_id, cart=cart)
    try:
        quantity = int(request.POST.get("quantity", 1))
    except (TypeError, ValueError):
        quantity = 1
    if quantity <= 0:
        item.delete()
        messages.info(request, "Товар удалён из корзины.")
    else:
        item.quantity = quantity
        item.save(update_fields=["quantity"])
        messages.success(request, "Корзина обновлена.")
    return redirect("orders:cart")


@login_required
@require_POST
def remove_from_cart(request, item_id):
    cart = get_or_create_cart(request.user)
    CartItem.objects.filter(pk=item_id, cart=cart).delete()
    messages.info(request, "Item removed from your basket.")
    return redirect("orders:cart")


@login_required
def checkout(request):
    cart = get_or_create_cart(request.user)
    warehouse = get_current_warehouse(request)
    items = list(cart.items.select_related("product"))

    if not items:
        messages.warning(request, "Корзина пуста.")
        return redirect("orders:cart")
    if warehouse is None:
        messages.error(request, "К вашему аккаунту ещё не привязан склад.")
        return redirect("orders:cart")
    if not request.user.companies.exists():
        messages.error(
            request, "Добавьте компанию в профиле или обратитесь к менеджеру."
        )
        return redirect("orders:cart")

    # Availability = total stock across all warehouses (own + 7-day delivery),
    # so an order can be placed as long as the total covers it.
    stock_map = available_map([i.product_id for i in items])
    issues = []
    for item in items:
        item.available = stock_map.get(item.product_id, 0)
        if item.quantity > item.available:
            issues.append(item)

    if request.method == "POST":
        form = CheckoutForm(request.POST, user=request.user)
        if issues:
            messages.error(
                request,
                "Некоторых товаров не хватает на складе. "
                "Измените количество в корзине.",
            )
        elif form.is_valid():
            try:
                with transaction.atomic():
                    delivery_method = form.cleaned_data["delivery_method"]
                    if delivery_method == Order.DeliveryMethod.PICKUP:
                        address = ""
                    else:
                        new_addr = form.cleaned_data["new_delivery_address"].strip()
                        if new_addr:
                            address = DeliveryAddress.objects.create(
                                user=request.user, address=new_addr[:255]
                            ).address
                        else:
                            address = form.cleaned_data["delivery_address"].address
                    order = Order.objects.create(
                        user=request.user,
                        warehouse=warehouse,
                        company=form.cleaned_data["company"],
                        payment_method=form.cleaned_data["payment_method"],
                        delivery_method=delivery_method,
                        shipping_address=address,
                        comment=form.cleaned_data["comment"],
                    )
                    own_ids = own_warehouse_ids(request.user)
                    for item in items:
                        stock_rows = list(
                            Stock.objects.select_for_update().filter(
                                product=item.product, warehouse__is_active=True
                            )
                        )
                        if sum(s.quantity for s in stock_rows) < item.quantity:
                            raise ValueError("stock changed")
                        # Fulfil from own warehouses first, then others (7-day),
                        # taking from the largest holdings first.
                        stock_rows.sort(
                            key=lambda s: (s.warehouse_id not in own_ids, -s.quantity)
                        )
                        remaining = item.quantity
                        for stock in stock_rows:
                            if remaining <= 0:
                                break
                            take = min(stock.quantity, remaining)
                            if take:
                                stock.quantity -= take
                                stock.save(update_fields=["quantity"])
                                remaining -= take
                        OrderItem.objects.create(
                            order=order,
                            product=item.product,
                            sku=item.product.sku,
                            name=item.product.name,
                            price=item.unit_price,
                            quantity=item.quantity,
                        )
                    order.recalculate_total()
                    cart.items.all().delete()
            except (ValueError, Stock.DoesNotExist):
                messages.error(
                    request,
                    "Остатки изменились при оформлении заказа. Проверьте корзину.",
                )
                return redirect("orders:cart")
            messages.success(request, f"Заказ №{order.pk} успешно оформлен.")
            send_order_emails(order)
            return redirect("orders:order_detail", pk=order.pk)
    else:
        form = CheckoutForm(user=request.user)

    return render(
        request,
        "orders/checkout.html",
        {
            "cart": cart,
            "items": items,
            "warehouse": warehouse,
            "form": form,
            "issues": issues,
        },
    )


@login_required
def order_list(request):
    orders = request.user.orders.select_related("warehouse", "company")
    return render(request, "orders/order_list.html", {"orders": orders})


@login_required
def order_detail(request, pk):
    order = get_object_or_404(
        Order.objects.select_related("warehouse").prefetch_related("items__product"),
        pk=pk,
        user=request.user,
    )
    return render(request, "orders/order_detail.html", {"order": order})


@login_required
@require_POST
def cancel_order(request, pk):
    order = get_object_or_404(request.user.orders, pk=pk)
    next_url = request.POST.get("next")
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = reverse("orders:order_detail", args=[order.pk])
    if not order.is_cancellable:
        messages.error(request, "Этот заказ уже нельзя отменить.")
        return redirect(next_url)
    order.status = Order.Status.CANCELLED
    order.save(update_fields=["status", "updated_at"])
    try:
        send_order_cancellation(order)
    except Exception:  # noqa: BLE001
        logger.exception(
            "Order #%s: cancellation notice to warehouse failed", order.pk
        )
    messages.success(request, f"Заказ №{order.pk} отменён.")
    return redirect(next_url)


@login_required
def order_invoice(request, pk):
    qs = Order.objects.all() if request.user.is_staff else request.user.orders.all()
    order = get_object_or_404(
        qs.select_related("user", "warehouse").prefetch_related("items__product"),
        pk=pk,
    )
    content = build_invoice_xlsx(order)
    response = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    filename = f"Счёт №{order.invoice_number}.xlsx"
    response["Content-Disposition"] = (
        f"attachment; filename=invoice_{order.invoice_number}.xlsx; "
        f"filename*=UTF-8''{quote(filename)}"
    )
    return response


@login_required
@require_POST
def toggle_favorite(request, product_id):
    product = get_object_or_404(Product, pk=product_id, is_active=True)
    fav = Favorite.objects.filter(user=request.user, product=product).first()
    if fav:
        fav.delete()
        messages.info(request, f"{product.name} удалён из избранного.")
    else:
        Favorite.objects.create(user=request.user, product=product)
        messages.success(request, f"{product.name} добавлен в избранное.")
    return redirect(request.POST.get("next") or "orders:wishlist")


@login_required
def wishlist(request):
    warehouse = get_current_warehouse(request)
    own_ids = own_warehouse_ids(request.user)
    price_type = price_type_for_user(request.user)
    fav_ids = list(
        request.user.favorites.order_by("-created_at").values_list(
            "product_id", flat=True
        )
    )
    by_id = {
        p.pk: p
        for p in annotate_availability(
            Product.objects.filter(pk__in=fav_ids, is_active=True).select_related(
                "brand"
            ),
            own_ids,
        )
    }
    products = []
    for pid in fav_ids:  # preserve "newest first" order
        product = by_id.get(pid)
        if product is not None:
            product.effective_price = product.price_for(price_type)
            products.append(product)
    return render(
        request,
        "orders/wishlist.html",
        {
            "products": products,
            "show_stock": True,
            "warehouse": warehouse,
            "favorite_ids": set(fav_ids),
            "price_type": price_type,
        },
    )
