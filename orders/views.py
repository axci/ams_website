from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from catalog.models import Product
from warehouses.models import Stock
from warehouses.selection import get_current_warehouse

from .emails import send_order_emails
from .forms import CheckoutForm
from .invoices import build_invoice_xlsx
from .models import CartItem, Order, OrderItem
from .utils import get_or_create_cart


def _stock_map(warehouse, products):
    """Map of product_id -> available quantity in the given warehouse."""
    if not warehouse:
        return {}
    rows = Stock.objects.filter(
        warehouse=warehouse, product__in=[p.product_id for p in products]
    )
    return {row.product_id: row.quantity for row in rows}


@login_required
def cart_detail(request):
    cart = get_or_create_cart(request.user)
    warehouse = get_current_warehouse(request)
    items = list(cart.items.select_related("product", "product__brand"))
    stock_map = _stock_map(warehouse, items)
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

    stock_map = _stock_map(warehouse, items)
    issues = []
    for item in items:
        item.available = stock_map.get(item.product_id, 0)
        if item.quantity > item.available:
            issues.append(item)

    if request.method == "POST":
        form = CheckoutForm(request.POST)
        if issues:
            messages.error(
                request,
                "Некоторых товаров не хватает на складе. "
                "Измените количество в корзине.",
            )
        elif form.is_valid():
            try:
                with transaction.atomic():
                    order = Order.objects.create(
                        user=request.user,
                        warehouse=warehouse,
                        shipping_address=form.cleaned_data["shipping_address"],
                        comment=form.cleaned_data["comment"],
                    )
                    for item in items:
                        stock = Stock.objects.select_for_update().get(
                            product=item.product, warehouse=warehouse
                        )
                        if stock.quantity < item.quantity:
                            raise ValueError("stock changed")
                        stock.quantity -= item.quantity
                        stock.save(update_fields=["quantity"])
                        OrderItem.objects.create(
                            order=order,
                            product=item.product,
                            sku=item.product.sku,
                            name=item.product.name,
                            price=item.product.price,
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
        form = CheckoutForm(initial={"shipping_address": request.user.company_name})

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
    orders = request.user.orders.select_related("warehouse")
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
    filename = f"Счёт №{order.pk}.xlsx"
    response["Content-Disposition"] = (
        f"attachment; filename=invoice_{order.pk}.xlsx; filename*=UTF-8''{quote(filename)}"
    )
    return response
