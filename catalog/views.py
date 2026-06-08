from decimal import Decimal, InvalidOperation

from django.core.paginator import Paginator
from django.db.models import IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render

from warehouses.models import Stock
from warehouses.selection import get_current_warehouse

from .models import BannerSlide, Brand, Category, Product


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

    if query:
        products = products.filter(
            Q(name__icontains=query)
            | Q(sku__icontains=query)
            | Q(article__icontains=query)
            | Q(manufacturer_number__icontains=query)
            | Q(brand__name__icontains=query)
            | Q(description__icontains=query)
        )
    if brand_slug:
        products = products.filter(brand__slug=brand_slug)
    if category_id.isdigit():
        products = products.filter(category_id=category_id)
    if subcategory_id.isdigit():
        products = products.filter(subcategory_id=subcategory_id)
    if volume_value:
        try:
            products = products.filter(volume=Decimal(volume_value))
        except (InvalidOperation, ValueError):
            volume_value = ""

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

    paginator = Paginator(products, 12)
    page_obj = paginator.get_page(request.GET.get("page"))

    # Show the rotating banner only on the clean landing page (no search/filter).
    is_landing = not any(
        [query, brand_slug, category_id, subcategory_id, volume_value, request.GET.get("page")]
    )
    banner_slides = (
        BannerSlide.objects.filter(is_active=True)[:7] if is_landing else []
    )

    volumes = (
        Product.objects.filter(is_active=True, volume__isnull=False)
        .values_list("volume", flat=True)
        .distinct()
        .order_by("volume")
    )

    context = {
        "banner_slides": banner_slides,
        "page_obj": page_obj,
        "warehouse": warehouse,
        "show_stock": show_stock,
        "brands": Brand.objects.all(),
        "categories": Category.objects.prefetch_related("subcategories"),
        "volumes": volumes,
        "query": query,
        "selected_brand": brand_slug,
        "selected_category": category_id,
        "selected_subcategory": subcategory_id,
        "selected_volume": volume_value,
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
    # Other products of the same model (e.g. different volumes), ordered by volume.
    variants = []
    if product.model_product_id:
        variants = list(
            Product.objects.filter(
                model_product_id=product.model_product_id, is_active=True
            ).order_by("volume", "name")
        )

    context = {
        "product": product,
        "warehouse": warehouse,
        "show_stock": show_stock,
        "stock_qty": stock_qty,
        "variants": variants,
    }
    return render(request, "catalog/product_detail.html", context)
