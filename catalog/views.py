import re
from decimal import Decimal

from django.core.paginator import Paginator
from django.db.models import DecimalField, F, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render

from warehouses.models import Stock
from warehouses.selection import get_current_warehouse

from .models import BannerSlide, Brand, Category, Product, ProductPrice, SubCategory
from .pricing import price_type_for_user


def _viscosity_key(value):
    """Sort viscosities numerically (0W20, 5W30, 10W40) rather than as text."""
    match = re.match(r"(\d+)W(\d+)", value)
    return (int(match.group(1)), int(match.group(2))) if match else (10**6, 10**6)


def _with_effective_price(products, price_type):
    """Annotate each product with `effective_price` for the given price type,
    falling back to the product's base `price` when no per-type price exists."""
    if price_type is not None:
        price_sub = ProductPrice.objects.filter(
            product=OuterRef("pk"), price_type=price_type
        ).values("price")[:1]
        return products.annotate(
            effective_price=Coalesce(
                Subquery(
                    price_sub,
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                ),
                F("price"),
            )
        )
    return products.annotate(effective_price=F("price"))


RECENT_KEY = "recently_viewed"
RECENT_STORE = 20  # product ids kept in the session
RECENT_SHOW = 6  # products shown in the block


def _remember_viewed(request, pk):
    """Record a product as recently viewed (newest first, deduped, capped)."""
    ids = [i for i in request.session.get(RECENT_KEY, []) if i != pk]
    ids.insert(0, pk)
    request.session[RECENT_KEY] = ids[:RECENT_STORE]


def _recently_viewed(request, price_type, exclude_pk=None, limit=RECENT_SHOW):
    """Recently viewed products (session-based), newest first, price-annotated."""
    ids = [i for i in request.session.get(RECENT_KEY, []) if i != exclude_pk]
    if not ids:
        return []
    products = _with_effective_price(
        Product.objects.filter(pk__in=ids, is_active=True).select_related("brand"),
        price_type,
    )
    by_id = {p.pk: p for p in products}
    result = []
    for i in ids:
        product = by_id.get(i)
        if product is not None:
            result.append(product)
        if len(result) >= limit:
            break
    return result


def product_list(request):
    # Public page: anyone may browse. Stock is only revealed to a logged-in
    # buyer who has a current (assigned) warehouse.
    warehouse = get_current_warehouse(request)
    show_stock = warehouse is not None
    products = Product.objects.filter(is_active=True).select_related(
        "brand", "category", "subcategory"
    )

    query = request.GET.get("q", "").strip()
    brand_slug = request.GET.get("brand", "")
    category_id = request.GET.get("category", "")
    subcategory_id = request.GET.get("subcategory", "")
    volume_value = request.GET.get("volume", "")
    viscosity_value = request.GET.get("viscosity", "")
    in_stock = request.GET.get("in_stock") == "1"

    if query:
        products = products.filter(
            Q(name__icontains=query)
            | Q(sku__icontains=query)
            | Q(article__icontains=query)
            | Q(manufacturer_number__icontains=query)
            | Q(brand__name__icontains=query)
            | Q(description__icontains=query)
        )
    # Brand → categories cascade. Which categories a brand offers is set in the
    # admin (Brand.categories); empty means "all categories".
    brand_obj = Brand.objects.filter(slug=brand_slug).first() if brand_slug else None
    categories_qs = Category.objects.prefetch_related("subcategories")
    if brand_obj and brand_obj.categories.exists():
        categories_qs = categories_qs.filter(brands=brand_obj)
    categories = list(categories_qs)
    allowed_cat_ids = {c.id for c in categories}

    # Drop selections that no longer fit the cascade (e.g. a category not sold by
    # the chosen brand, or a subcategory outside the chosen category).
    if category_id.isdigit() and int(category_id) not in allowed_cat_ids:
        category_id = ""
    if subcategory_id.isdigit():
        sub = SubCategory.objects.filter(pk=subcategory_id).first()
        if sub is None:
            subcategory_id = ""
        elif category_id.isdigit():
            if str(sub.category_id) != category_id:
                subcategory_id = ""
        elif sub.category_id not in allowed_cat_ids:
            subcategory_id = ""

    if brand_slug:
        products = products.filter(brand__slug=brand_slug)
    if category_id.isdigit():
        products = products.filter(category_id=category_id)
    if subcategory_id.isdigit():
        products = products.filter(subcategory_id=subcategory_id)

    # Volumes and viscosities available for the current brand/category/subcategory.
    # Distinct (volume, unit) pairs so the filter shows the real unit per size
    # (e.g. "450 мл" and "5 л"), now that units are per-product.
    volumes = [
        {"token": f"{v}|{u}", "value": v, "unit": u}
        for v, u in products.filter(volume__isnull=False)
        .values_list("volume", "volume_unit")
        .distinct()
        .order_by("volume_unit", "volume")
    ]
    viscosities = sorted(
        set(products.exclude(viscosity="").values_list("viscosity", flat=True)),
        key=_viscosity_key,
    )
    # Apply the volume filter only if that (volume, unit) option is available.
    if volume_value:
        if volume_value in {opt["token"] for opt in volumes}:
            raw_value, _, raw_unit = volume_value.partition("|")
            products = products.filter(volume=Decimal(raw_value), volume_unit=raw_unit)
        else:
            volume_value = ""
    # Apply the viscosity filter only if that viscosity is actually available.
    if viscosity_value:
        if viscosity_value in viscosities:
            products = products.filter(viscosity=viscosity_value)
        else:
            viscosity_value = ""

    # Annotate each product with the quantity available in the current warehouse.
    if show_stock:
        stock_subquery = Stock.objects.filter(
            product=OuterRef("pk"), warehouse=warehouse
        ).values("quantity")[:1]
        products = products.annotate(
            stock_qty=Coalesce(
                Subquery(stock_subquery, output_field=IntegerField()), Value(0)
            )
        )
    else:
        products = products.annotate(stock_qty=Value(0, output_field=IntegerField()))

    # "Show in stock only" — only meaningful when the buyer can see stock.
    if in_stock and show_stock:
        products = products.filter(stock_qty__gt=0)

    # Prices shown depend on the viewer's price type (guests → «Розничные»).
    price_type = price_type_for_user(request.user)
    products = _with_effective_price(products, price_type)

    paginator = Paginator(products, 12)
    page_obj = paginator.get_page(request.GET.get("page"))

    # Show the rotating banner only on the clean landing page (no search/filter).
    is_landing = not any(
        [query, brand_slug, category_id, subcategory_id, volume_value, viscosity_value, in_stock, request.GET.get("page")]
    )
    banner_slides = (
        BannerSlide.objects.filter(is_active=True)[:7] if is_landing else []
    )

    context = {
        "banner_slides": banner_slides,
        "page_obj": page_obj,
        "warehouse": warehouse,
        "show_stock": show_stock,
        "brands": Brand.objects.all(),
        "categories": categories,
        "volumes": volumes,
        "viscosities": viscosities,
        "query": query,
        "selected_brand": brand_slug,
        "selected_category": category_id,
        "selected_subcategory": subcategory_id,
        "selected_volume": volume_value,
        "selected_viscosity": viscosity_value,
        "selected_in_stock": "1" if in_stock else "",
        "price_type": price_type,
        "recently_viewed": _recently_viewed(request, price_type),
    }
    return render(request, "catalog/product_list.html", context)


def product_detail(request, pk):
    product = get_object_or_404(
        Product.objects.select_related(
            "brand", "category", "subcategory", "model_product"
        ),
        pk=pk,
        is_active=True,
    )
    warehouse = get_current_warehouse(request)
    show_stock = warehouse is not None
    stock_qty = 0
    if show_stock:
        stock = Stock.objects.filter(product=product, warehouse=warehouse).first()
        stock_qty = stock.quantity if stock else 0
    # Price shown depends on the viewer's price type (guests → «Розничные»).
    price_type = price_type_for_user(request.user)
    price = product.price_for(price_type)
    # Other products of the same model (e.g. different volumes), ordered by volume.
    variants = []
    if product.model_product_id:
        variants = list(
            _with_effective_price(
                Product.objects.filter(
                    model_product_id=product.model_product_id, is_active=True
                ),
                price_type,
            ).order_by("volume", "name")
        )

    # Recently viewed (excluding this product), then record this view.
    recently_viewed = _recently_viewed(request, price_type, exclude_pk=product.pk)
    _remember_viewed(request, product.pk)

    context = {
        "product": product,
        "warehouse": warehouse,
        "show_stock": show_stock,
        "stock_qty": stock_qty,
        "variants": variants,
        "price": price,
        "price_type": price_type,
        "recently_viewed": recently_viewed,
    }
    return render(request, "catalog/product_detail.html", context)
