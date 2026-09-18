import logging
from datetime import timedelta
from decimal import Decimal
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import (
    Case,
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    Max,
    Min,
    Q,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce, TruncDay, TruncMonth, TruncWeek
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.models import DeliveryAddress
from catalog.models import Brand, ModelProduct, Product
from catalog.pricing import price_type_for_user
from warehouses.availability import (
    annotate_availability,
    own_available_map,
    own_warehouse_ids,
)
from warehouses.models import Stock, Warehouse
from warehouses.transit import TRANSIT_PARENTS
from warehouses.selection import get_current_warehouse

from .emails import send_order_cancellation, send_order_emails
from .forms import CheckoutForm
from .invoices import build_invoice_xlsx
from .models import CartItem, Favorite, Order, OrderItem, SalesRecord, StockSnapshot
from .sales_export import build_sales_xlsx
from .utils import get_or_create_cart

logger = logging.getLogger(__name__)

# Short Russian month names (index = month number) for chart labels.
RU_MONTHS_SHORT = [
    "", "янв", "фев", "мар", "апр", "май", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
]

# weight_unit variants → factor to convert a product's weight to kilograms, so
# sales in weight can be summed regardless of how the unit was entered.
_GRAM_UNITS = ["г", "гр", "г.", "гр.", "грамм", "граммов", "Г", "Гр", "ГР", "g", "gr", "gram"]
_TONNE_UNITS = ["т", "т.", "тн", "тонна", "тонн", "Т", "t", "T", "ton"]


@login_required
def cart_detail(request):
    cart = get_or_create_cart(request.user)
    warehouse = get_current_warehouse(request)
    items = list(cart.items.select_related("product", "product__brand"))
    # Ordering is limited to the buyer's own warehouse stock.
    stock_map = own_available_map(request.user, [i.product_id for i in items])
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
    next_url = request.POST.get("next") or "catalog:product_list"
    available = own_available_map(request.user, [product.pk]).get(product.pk, 0)
    existing = (
        cart.items.filter(product=product).values_list("quantity", flat=True).first()
        or 0
    )
    if existing + quantity > available:
        if available <= 0:
            messages.error(request, f"«{product.name}» нет в наличии на вашем складе.")
        else:
            in_cart = f", в корзине уже {existing} шт." if existing else ""
            messages.error(
                request,
                f"«{product.name}»: на складе {available} шт.{in_cart} "
                "Добавить больше нельзя.",
            )
        return redirect(next_url)

    item, created = CartItem.objects.get_or_create(
        cart=cart, product=product, defaults={"quantity": quantity}
    )
    if not created:
        item.quantity += quantity
        item.save(update_fields=["quantity"])
    messages.success(request, f"{product.name} добавлен в корзину.")
    return redirect(next_url)


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
        return redirect("orders:cart")
    available = own_available_map(request.user, [item.product_id]).get(
        item.product_id, 0
    )
    if quantity > available:
        if available <= 0:
            messages.error(
                request, f"«{item.product.name}» нет в наличии на вашем складе."
            )
        else:
            messages.error(
                request,
                f"«{item.product.name}»: на складе только {available} шт.",
            )
        return redirect("orders:cart")
    item.quantity = quantity
    item.save(update_fields=["quantity"])
    messages.success(request, "Корзина обновлена.")
    return redirect("orders:cart")


@login_required
@require_POST
def update_cart(request):
    """Update the quantities of every cart line at once (one «Обновить корзину»
    button). Each row posts quantity_<item_id>. A line set to 0 is removed; a
    line exceeding stock is left unchanged and reported."""
    cart = get_or_create_cart(request.user)
    items = list(cart.items.select_related("product"))
    stock_map = own_available_map(request.user, [i.product_id for i in items])
    changed = False
    for item in items:
        raw = request.POST.get(f"quantity_{item.pk}")
        if raw is None:
            continue
        try:
            quantity = int(raw)
        except (TypeError, ValueError):
            continue
        if quantity <= 0:
            item.delete()
            changed = True
            continue
        if quantity == item.quantity:
            continue
        available = stock_map.get(item.product_id, 0)
        if quantity > available:
            if available <= 0:
                messages.error(
                    request,
                    f"«{item.product.name}» нет в наличии на вашем складе — "
                    "количество не изменено.",
                )
            else:
                messages.error(
                    request,
                    f"«{item.product.name}»: на складе только {available} шт. — "
                    "количество не изменено.",
                )
            continue
        item.quantity = quantity
        item.save(update_fields=["quantity"])
        changed = True
    if changed:
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

    # Ordering is limited to the buyer's own warehouse stock.
    stock_map = own_available_map(request.user, [i.product_id for i in items])
    issues = []
    for item in items:
        item.available = stock_map.get(item.product_id, 0)
        if item.quantity > item.available:
            issues.append(item)

    if request.method == "POST":
        form = CheckoutForm(request.POST, user=request.user, cart_total=cart.total)
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
                        # Fulfil from the buyer's own warehouses only.
                        stock_rows = list(
                            Stock.objects.select_for_update().filter(
                                product=item.product,
                                warehouse_id__in=own_ids,
                                warehouse__is_active=True,
                            )
                        )
                        if sum(s.quantity for s in stock_rows) < item.quantity:
                            raise ValueError("stock changed")
                        # Take from the largest holdings first.
                        stock_rows.sort(key=lambda s: -s.quantity)
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
        form = CheckoutForm(user=request.user, cart_total=cart.total)

    return render(
        request,
        "orders/checkout.html",
        {
            "cart": cart,
            "items": items,
            "warehouse": warehouse,
            "form": form,
            "issues": issues,
            "free_delivery_min": request.user.free_delivery_min,
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


def can_view_sales(user):
    """Authorisation for the «Статистика продаж» section."""
    return user.is_superuser or getattr(user, "can_view_sales", False)


@login_required
def sales_stats(request):
    """Role-gated external sales statistics (imported from 1C). Filterable by
    date range and warehouse, with totals over the whole filtered set."""
    if not can_view_sales(request.user):
        raise PermissionDenied

    records = SalesRecord.objects.select_related("warehouse", "product", "product__brand")

    warehouse_id = request.GET.get("warehouse") or ""
    brand_id = request.GET.get("brand") or ""
    model_id = request.GET.get("model") or ""
    q = (request.GET.get("q") or "").strip()
    date_from = (request.GET.get("from") or "").strip()
    date_to = (request.GET.get("to") or "").strip()

    # The free-text search (`q`) matches many products by substring, so a code
    # that is a prefix of others narrows to several skus and the single-product
    # stock line is dropped. The product page instead links with an exact
    # `product` id, pinning the view to one product so its stock line always
    # shows. A typed query wins, letting the user search away from the product.
    selected_product = None
    if not q:
        product_pk = (request.GET.get("product") or "").strip()
        if product_pk.isdigit():
            selected_product = Product.objects.filter(pk=product_pk).first()
    sku_exact = selected_product.sku if selected_product and selected_product.sku else ""

    if warehouse_id:
        records = records.filter(warehouse_id=warehouse_id)
    if brand_id:
        records = records.filter(product__brand_id=brand_id)
    if model_id:
        records = records.filter(product__model_product_id=model_id)
    if sku_exact:
        records = records.filter(sku=sku_exact)
    elif q:
        records = records.filter(Q(sku__icontains=q) | Q(product__name__icontains=q))
    # Non-date filters applied — reused for the month/year-to-date windows, which
    # use their own date ranges and ignore the from/to filter.
    base = records
    if date_from:
        records = records.filter(date__date__gte=date_from)
    if date_to:
        records = records.filter(date__date__lte=date_to)

    if request.GET.get("export") == "xlsx":
        filename = f"продажи_{timezone.localdate():%d.%m.%Y}.xlsx"
        response = HttpResponse(
            build_sales_xlsx(records),
            content_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )
        response["Content-Disposition"] = (
            f"attachment; filename=sales.xlsx; filename*=UTF-8''{quote(filename)}"
        )
        return response

    # Metric: units (штуки) or weight (продажи × вес товара). Rows without a
    # product weight contribute nothing to weight totals.
    metric = "weight" if request.GET.get("metric") == "weight" else "qty"
    if metric == "weight":
        weight_field = DecimalField(max_digits=18, decimal_places=6)
        # Normalise each product's weight to kilograms — weight_unit may be
        # граммы or тонны, which must not be summed together as-is.
        to_kg = Case(
            When(product__weight_unit__in=_GRAM_UNITS, then=Value(Decimal("0.001"))),
            When(product__weight_unit__in=_TONNE_UNITS, then=Value(Decimal("1000"))),
            default=Value(Decimal("1")),
            output_field=weight_field,
        )
        row_expr = ExpressionWrapper(
            F("quantity") * F("product__weight") * to_kg, output_field=weight_field
        )
        # Products without a weight contribute 0 (and sort last), not NULL.
        value_expr = Coalesce(row_expr, Value(0), output_field=weight_field)
        metric_unit = "кг"
    else:
        value_expr = F("quantity")
        row_expr = F("quantity")
        metric_unit = "шт"

    totals = records.aggregate(
        val=Sum(value_expr), n=Count("id"), clients=Count("client", distinct=True)
    )
    page = Paginator(
        records.annotate(row_value=row_expr), 50
    ).get_page(request.GET.get("page"))

    # Month- and year-to-date vs the same period last year. Same metric and
    # non-date filters; own date windows (the from/to filter does not apply).
    now = timezone.now()

    def _shift_year(dt):
        try:
            return dt.replace(year=dt.year - 1)
        except ValueError:  # 29 February
            return dt.replace(year=dt.year - 1, day=28)

    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    year_start = month_start.replace(month=1)

    def _window(start, end):
        return float(
            base.filter(date__gte=start, date__lte=end).aggregate(
                v=Sum(value_expr)
            )["v"]
            or 0
        )

    def _period(start):
        cur = _window(start, now)
        prev = _window(_shift_year(start), _shift_year(now))
        pct = ((cur - prev) / prev * 100) if prev else None
        return {
            "cur": cur,
            "prev": prev,
            "pct": pct,
            "has_prev": prev > 0,
            "up": pct is not None and pct >= 0,
        }

    mtd = _period(month_start)
    ytd = _period(year_start)

    # Time series at three granularities (client switches without a reload).
    dated = records.exclude(date__isnull=True)

    def _series(trunc, label):
        rows = (
            dated.annotate(bucket=trunc("date"))
            .values("bucket")
            .annotate(q=Sum(value_expr))
            .order_by("bucket")
        )
        return [[label(r["bucket"]), float(r["q"] or 0)] for r in rows]

    def _day_series():
        # Continuous daily series (gaps filled with 0) carrying a trailing
        # 30-day moving average of daily sales, so the client can overlay a
        # smoothed line. Same metric as the bars; near the start the window is
        # whatever days exist so far.
        rows = list(
            dated.annotate(bucket=TruncDay("date"))
            .values("bucket")
            .annotate(q=Sum(value_expr))
            .order_by("bucket")
        )
        if not rows:
            return []
        by_day = {r["bucket"].date(): float(r["q"] or 0) for r in rows}
        day, end = rows[0]["bucket"].date(), rows[-1]["bucket"].date()
        days = []
        while day <= end:
            days.append(day)
            day += timedelta(days=1)
        vals = [by_day.get(d, 0.0) for d in days]
        window = 30
        out = []
        for i, d in enumerate(days):
            seg = vals[max(0, i - window + 1): i + 1]
            out.append([d.strftime("%d.%m.%Y"), vals[i], round(sum(seg) / len(seg), 3)])
        return out

    chart_time = {
        "day": _day_series(),
        "week": _series(TruncWeek, lambda d: d.strftime("%d.%m.%Y")),
    }

    # Monthly view: a day-by-day stock line with sales bars that span each whole
    # month. Same non-date filters; the date range still narrows it.
    stock_snaps = StockSnapshot.objects.all()
    if warehouse_id:
        stock_snaps = stock_snaps.filter(warehouse_id=warehouse_id)
    if brand_id:
        stock_snaps = stock_snaps.filter(product__brand_id=brand_id)
    if model_id:
        stock_snaps = stock_snaps.filter(product__model_product_id=model_id)
    if sku_exact:
        stock_snaps = stock_snaps.filter(sku=sku_exact)
    elif q:
        stock_snaps = stock_snaps.filter(Q(sku__icontains=q) | Q(product__name__icontains=q))
    if date_from:
        stock_snaps = stock_snaps.filter(date__gte=date_from)
    if date_to:
        stock_snaps = stock_snaps.filter(date__lte=date_to)
    # The day-by-day stock line is only meaningful for a single product; with
    # many products together it is dropped. `.order_by()` clears the model's
    # Meta ordering so DISTINCT counts skus (not sku+warehouse+date tuples) and
    # the daily sum groups by date alone (across all warehouses). It is also
    # hidden in weight mode — stock is tracked in units and must not share the
    # kilogram sales axis.
    show_stock_line = (
        metric != "weight"
        and stock_snaps.order_by().values("sku").distinct().count() == 1
    )
    daily_stock = {}
    if show_stock_line:
        daily_stock = {
            r["date"]: float(r["q"] or 0)
            for r in stock_snaps.order_by().values("date").annotate(q=Sum("quantity"))
        }

    # Inventory turnover in days = average day-by-day stock ÷ average daily units
    # sold, over the period stock is tracked for. Summing every daily snapshot's
    # quantity gives «unit-days» of stock; dividing by units sold in the same
    # window collapses the day count and yields days directly. Units (штуки) for
    # both — stock carries no weight — so it ignores the units/weight toggle and
    # honours the current filters (including a single pinned product).
    turnover_days = None
    span = stock_snaps.aggregate(a=Min("date"), b=Max("date"), s=Sum("quantity"))
    if span["a"]:
        sold = (
            base.filter(date__date__gte=span["a"], date__date__lte=span["b"])
            .aggregate(s=Sum("quantity"))["s"]
            or 0
        )
        if sold:
            turnover_days = float(span["s"] or 0) / float(sold)

    month_sales = {}
    for row in (
        dated.annotate(bucket=TruncMonth("date")).values("bucket").annotate(q=Sum(value_expr))
    ):
        b = row["bucket"]
        month_sales[(b.year, b.month)] = float(row["q"] or 0)

    # Daily axis over the whole period (sales days ∪ stock days). Each day carries
    # its month's total sales (so equal-height bars form a block per month) and
    # that day's stock.
    bounds = []
    srange = dated.aggregate(a=Min("date"), b=Max("date"))
    if srange["a"]:
        bounds += [srange["a"].date(), srange["b"].date()]
    if daily_stock:
        bounds += [min(daily_stock), max(daily_stock)]
    chart_month = {"labels": [], "sales": [], "stock": []}
    if bounds:
        day, end = min(bounds), max(bounds)
        while day <= end:
            chart_month["labels"].append(day.strftime("%d.%m.%Y"))
            chart_month["sales"].append(month_sales.get((day.year, day.month), 0.0))
            chart_month["stock"].append(daily_stock.get(day))
            day += timedelta(days=1)

    # By client: top 10 by расход, the rest summed into «Другие».
    client_rows = list(
        records.exclude(client="")
        .values("client")
        .annotate(q=Sum(value_expr))
        .order_by("-q")
    )
    labels = [r["client"] for r in client_rows[:10]]
    values = [float(r["q"] or 0) for r in client_rows[:10]]
    others = sum(float(r["q"] or 0) for r in client_rows[10:])
    if others > 0:
        labels.append("Другие")
        values.append(others)
    chart_clients = {"labels": labels, "values": values}

    # By warehouse (all warehouses present in the filtered set). `ids` lets the
    # chart link each bar to that warehouse's stats.
    wh_rows = (
        records.values("warehouse", "warehouse__name")
        .annotate(q=Sum(value_expr))
        .order_by("-q")
    )
    chart_warehouses = {
        "labels": [r["warehouse__name"] for r in wh_rows],
        "values": [float(r["q"] or 0) for r in wh_rows],
        "ids": [r["warehouse"] for r in wh_rows],
    }

    # Rankings by расход (descending), top 50 each — respect the active filters.
    def _rank(field, default):
        return [
            {"label": r[field] or default, "qty": float(r["q"] or 0)}
            for r in records.values(field)
            .annotate(q=Sum(value_expr))
            .order_by("-q")[:50]
        ]

    by_product = [
        {"label": r["product__name"] or r["sku"], "sku": r["sku"],
         "pk": r["product_id"], "qty": float(r["q"] or 0)}
        for r in records.values("sku", "product__name", "product_id")
        .annotate(q=Sum(value_expr))
        .order_by("-q")[:50]
    ]
    by_model = [
        {"label": r["product__model_product__name"] or "— без модели",
         "pk": r["product__model_product"], "qty": float(r["q"] or 0)}
        for r in records.values("product__model_product", "product__model_product__name")
        .annotate(q=Sum(value_expr))
        .order_by("-q")[:50]
    ]
    by_category = _rank("product__category__name", "— без категории")
    by_subcategory = _rank("product__subcategory__name", "— без подкатегории")

    # Everything except `page`, so pagination links keep the active filters.
    params = request.GET.copy()
    params.pop("page", None)

    # Model drill-down: keep the other filters, swap the model.
    mp = request.GET.copy()
    mp.pop("page", None)
    mp.pop("model", None)
    model_qs = mp.urlencode()
    model_link_base = "?" + (model_qs + "&" if model_qs else "") + "model="
    selected_model = ModelProduct.objects.filter(pk=model_id).first() if model_id else None

    # Product drill-down: clicking a product in the «Товары» table opens its own
    # sales statistics (an exact `product` pin), keeping the other filters. Drop
    # the free-text `q`, which the exact product id replaces.
    pp = request.GET.copy()
    for k in ("page", "q", "product"):
        pp.pop(k, None)
    prod_qs = pp.urlencode()
    product_link_base = "?" + (prod_qs + "&" if prod_qs else "") + "product="

    # Sibling products (same model) for quick-switch buttons in the product block.
    product_variants = []
    if selected_product and selected_product.model_product_id:
        product_variants = list(
            Product.objects.filter(
                model_product_id=selected_product.model_product_id, is_active=True
            ).order_by("volume", "weight", "name")
        )

    # Current live stock (from the 1C sync) for a pinned product: total and per
    # active warehouse.
    current_stock = None
    if selected_product:
        stock_rows = list(
            Stock.objects.filter(product=selected_product, warehouse__is_active=True)
            .select_related("warehouse")
            .order_by("-quantity", "warehouse__name")
        )
        # Transit warehouses (goods in transit) are kept off the charts but shown
        # here under the main warehouse they feed. Only non-empty ones.
        transit_rows = Stock.objects.filter(
            product=selected_product, warehouse__name__in=TRANSIT_PARENTS
        ).select_related("warehouse")
        transit = sorted(
            (
                {"name": TRANSIT_PARENTS[s.warehouse.name], "qty": s.quantity}
                for s in transit_rows
                if s.quantity
            ),
            key=lambda r: (-r["qty"], r["name"]),
        )
        current_stock = {
            "rows": [{"name": s.warehouse.name, "qty": s.quantity} for s in stock_rows],
            "total": sum(s.quantity for s in stock_rows),
            "transit": transit,
            "transit_total": sum(r["qty"] for r in transit),
        }

    # Metric toggle (units / weight): keep the other filters, swap the metric.
    metp = request.GET.copy()
    metp.pop("page", None)
    metp.pop("metric", None)
    met_qs = metp.urlencode()
    metric_link_base = "?" + (met_qs + "&" if met_qs else "") + "metric="

    # Warehouse drill-down: clicking a bar in «Продажи по складам» filters to it.
    whp = request.GET.copy()
    whp.pop("page", None)
    whp.pop("warehouse", None)
    wh_link_qs = whp.urlencode()
    warehouse_link_base = "?" + (wh_link_qs + "&" if wh_link_qs else "") + "warehouse="

    # Quick date-range shortcuts (last 30 / 60 days): links that set `from` and
    # clear `to`, keeping the other filters. Highlight whichever is active.
    today = timezone.localdate()
    d30 = (today - timedelta(days=30)).isoformat()
    d60 = (today - timedelta(days=60)).isoformat()
    dp = request.GET.copy()
    for k in ("page", "from", "to"):
        dp.pop(k, None)
    date_qs = dp.urlencode()
    date_link_base = "?" + (date_qs + "&" if date_qs else "") + "from="
    active_range = None
    if not date_to and date_from == d30:
        active_range = 30
    elif not date_to and date_from == d60:
        active_range = 60

    return render(
        request,
        "orders/sales_stats.html",
        {
            "page_obj": page,
            "totals": totals,
            "warehouses": Warehouse.objects.filter(is_active=True).order_by("name"),
            "brands": Brand.objects.filter(
                products__sales_records__isnull=False
            ).distinct().order_by("name"),
            "selected_warehouse": warehouse_id,
            "selected_brand": brand_id,
            "selected_product": selected_product,
            "q": q,
            "date_from": date_from,
            "date_to": date_to,
            "base_qs": params.urlencode(),
            "chart_time": chart_time,
            "chart_month": chart_month,
            "show_stock_line": show_stock_line,
            "turnover_days": turnover_days,
            "chart_clients": chart_clients,
            "chart_warehouses": chart_warehouses,
            "by_product": by_product,
            "by_model": by_model,
            "by_category": by_category,
            "by_subcategory": by_subcategory,
            "model_link_base": model_link_base,
            "model_qs": model_qs,
            "product_link_base": product_link_base,
            "product_variants": product_variants,
            "current_stock": current_stock,
            "selected_model": selected_model,
            "metric": metric,
            "metric_unit": metric_unit,
            "metric_link_base": metric_link_base,
            "warehouse_link_base": warehouse_link_base,
            "date_link_base": date_link_base,
            "d30": d30,
            "d60": d60,
            "active_range": active_range,
            "mtd": mtd,
            "ytd": ytd,
        },
    )


@login_required
def stock_history(request):
    """Role-gated stock-over-time chart. Pick a product (code or name) and
    optionally a warehouse; each (product × warehouse) is a line over the
    imported period. Capped at 12 lines — narrow the search for more."""
    if not can_view_sales(request.user):
        raise PermissionDenied

    q = (request.GET.get("q") or "").strip()
    warehouse_id = request.GET.get("warehouse") or ""
    chart = {"labels": [], "series": []}
    too_many = False

    # The product page links here with an exact `product` id; a typed query wins.
    selected_product = None
    if not q:
        product_pk = (request.GET.get("product") or "").strip()
        if product_pk.isdigit():
            selected_product = Product.objects.filter(pk=product_pk).first()
    sku_exact = selected_product.sku if selected_product and selected_product.sku else ""

    if q or sku_exact:
        snaps = StockSnapshot.objects.all()
        if warehouse_id:
            snaps = snaps.filter(warehouse_id=warehouse_id)
        if sku_exact:
            snaps = snaps.filter(sku=sku_exact)
        else:
            snaps = snaps.filter(Q(sku__icontains=q) | Q(product__name__icontains=q))
        rows = list(
            snaps.order_by("date").values(
                "sku", "product__name", "warehouse__name", "date", "quantity"
            )
        )
        dates = sorted({r["date"] for r in rows})
        idx = {d: i for i, d in enumerate(dates)}
        series = {}
        for r in rows:
            key = (r["sku"], r["warehouse__name"])
            s = series.get(key)
            if s is None:
                if len(series) >= 12:
                    too_many = True
                    continue
                label = (r["product__name"] or r["sku"]) + " — " + r["warehouse__name"]
                s = {"label": label, "data": [None] * len(dates)}
                series[key] = s
            s["data"][idx[r["date"]]] = float(r["quantity"])
        chart = {
            "labels": [d.strftime("%d.%m.%Y") for d in dates],
            "series": list(series.values()),
        }

    return render(
        request,
        "orders/stock_history.html",
        {
            "q": q,
            "selected_product": selected_product,
            "warehouses": Warehouse.objects.filter(is_active=True).order_by("name"),
            "selected_warehouse": warehouse_id,
            "chart": chart,
            "too_many": too_many,
            "has_data": bool(chart["series"]),
        },
    )
