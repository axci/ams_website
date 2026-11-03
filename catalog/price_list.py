"""Build and email a price list (.xlsx) for a price type + warehouse.

Two layouts are available (see :data:`LAYOUTS`):

``standard``
    Артикул, Бренд, Наименование, Свободный остаток (stock on the chosen
    warehouse) and Цена (the chosen price type's price, falling back to the
    product's base price when that type has no explicit price), starting at A1.

``shop`` (интернет-магазин)
    The same data offset to column B, with a title on row 1 and the column
    headers on row 8 (products from row 9), plus Штрихкод (gtin), ТН ВЭД and
    Код ОКПД2 columns.

Both include only active products that have a price. A product under a split
brand (see :data:`BRAND_SPLITS`, e.g. «3ton/Country») is expanded across its
sub-brands and, if it has a manufacturer number, across {article, manufacturer
number} in the Артикул column — so one such product can produce up to four rows.
"""

from io import BytesIO

import openpyxl
from django.conf import settings
from django.core.mail import EmailMessage
from django.db.models import DecimalField, F, IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from warehouses.models import Stock

from .models import Product, ProductPrice

XLSX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

HEADERS = ["Артикул", "Бренд", "Наименование", "Свободный остаток", "Цена"]

# Brand names shown differently in the exported price list (display only — the
# catalog keeps the original name).
BRAND_LABEL_OVERRIDES = {
    "SCT (Germany)": "SCT",
    "Аляska": "Alaska",
}

# Combined brands that must appear in the price list as separate brands: a
# product under such a brand is listed once per sub-brand (its row duplicated).
# Keyed by _brand_key() so matching is case- and whitespace-insensitive.
BRAND_SPLITS = {
    "3ton/country": ["3ton", "Country"],
}


def _brand_key(name):
    """Normalise a brand name for matching (drop all spaces, casefold)."""
    return "".join((name or "").split()).casefold()


def _price_list_variants(product):
    """Yield (brand_label, article) pairs — the price-list row(s) for a product.

    A normal product yields one pair (its article, with any brand display
    override applied). A split brand (see :data:`BRAND_SPLITS`, e.g.
    «3ton/Country») is expanded across its sub-brands and, when the product has
    a manufacturer number, across {article, manufacturer_number} in the Артикул
    column — so such a product yields up to four rows.
    """
    brand_name = product.brand.name if product.brand_id else ""
    split = BRAND_SPLITS.get(_brand_key(brand_name))
    if not split:
        yield (BRAND_LABEL_OVERRIDES.get(brand_name, brand_name), product.article)
        return
    mfr = (product.manufacturer_number or "").strip()
    articles = [product.article, mfr] if mfr else [product.article]
    for brand_label in split:
        for article in articles:
            yield (brand_label, article)


def _price_list_products(price_type, warehouse, in_stock_only=False):
    """Active products annotated with the type's price and the warehouse stock."""
    price_sub = ProductPrice.objects.filter(
        product=OuterRef("pk"), price_type=price_type
    ).values("price")[:1]
    stock_sub = Stock.objects.filter(
        product=OuterRef("pk"), warehouse=warehouse
    ).values("quantity")[:1]
    products = (
        Product.objects.filter(is_active=True)
        .select_related("brand")
        .annotate(
            list_price=Coalesce(
                Subquery(
                    price_sub,
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                ),
                F("price"),
            ),
            free_stock=Coalesce(
                Subquery(stock_sub, output_field=IntegerField()), Value(0)
            ),
        )
    )
    # Never list a product with no price.
    products = products.filter(list_price__gt=0)
    if in_stock_only:
        products = products.filter(free_stock__gt=0)
    return products.order_by("brand__name", "name")


def build_price_list_xlsx(price_type, warehouse, in_stock_only=False):
    """Return the price list as .xlsx bytes."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Прайс"
    today = timezone.localdate().strftime("%d.%m.%Y")

    ws.append([f"Прайс «{price_type.name}» · склад {warehouse.name} · {today}"])
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(HEADERS))
    title = ws.cell(row=1, column=1)
    title.font = Font(bold=True, size=14)
    title.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 22

    ws.append(HEADERS)
    for cell in ws[2]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A3"

    for p in _price_list_products(price_type, warehouse, in_stock_only).iterator():
        for brand_label, article in _price_list_variants(p):
            ws.append([
                article,
                brand_label,
                p.name,
                p.free_stock,
                float(p.list_price or 0),
            ])

    for i, width in enumerate([18, 22, 50, 18, 14], start=1):
        ws.column_dimensions[get_column_letter(i)].width = width

    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()


# «интернет-магазин» layout: data offset to column B, a title on row 1 and the
# column headers on row 8, products from row 9. Column A is left blank.
SHOP_HEADERS = [
    "Бренд", "Артикул", "Штрихкод", "Наименование",
    "Свободный остаток", "ТН ВЭД", "Код ОКПД2", "Цена",
]
SHOP_FIRST_COL = 2   # column B (column A is left blank)
SHOP_HEADER_ROW = 8  # column labels on row 8
SHOP_DATA_ROW = 9    # products start on row 9
SHOP_WIDTHS = [22, 18, 16, 50, 16, 16, 18, 14]


def build_price_list_xlsx_shop(price_type, warehouse, in_stock_only=False):
    """Return the «интернет-магазин» price list as .xlsx bytes (see module doc)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Прайс"
    today = timezone.localdate().strftime("%d.%m.%Y")

    first = SHOP_FIRST_COL
    last = first + len(SHOP_HEADERS) - 1

    title = ws.cell(
        row=1, column=first,
        value=f"Прайс «{price_type.name}» · склад {warehouse.name} · {today}",
    )
    ws.merge_cells(start_row=1, start_column=first, end_row=1, end_column=last)
    title.font = Font(bold=True, size=14)
    title.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 22

    for offset, header in enumerate(SHOP_HEADERS):
        cell = ws.cell(row=SHOP_HEADER_ROW, column=first + offset, value=header)
        cell.font = Font(bold=True)
    ws.freeze_panes = f"{get_column_letter(first)}{SHOP_DATA_ROW}"

    row = SHOP_DATA_ROW
    for p in _price_list_products(price_type, warehouse, in_stock_only).iterator():
        for brand_label, article in _price_list_variants(p):
            values = [
                brand_label,
                article,
                p.gtin,
                p.name,
                p.free_stock,
                p.tnved,
                p.okpd,
                float(p.list_price or 0),
            ]
            for offset, value in enumerate(values):
                ws.cell(row=row, column=first + offset, value=value)
            row += 1

    for offset, width in enumerate(SHOP_WIDTHS):
        ws.column_dimensions[get_column_letter(first + offset)].width = width

    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()


# Layout name (chosen by the admin action) → builder.
LAYOUTS = {
    "standard": build_price_list_xlsx,
    "shop": build_price_list_xlsx_shop,
}


def send_price_list_email(
    price_type, warehouse, recipients, in_stock_only=False, layout="standard"
):
    """Build the price list and email it as an .xlsx attachment.

    `recipients` is a list of addresses. `layout` is a key of :data:`LAYOUTS`
    ('standard' or 'shop'). Raises on send failure."""
    data = LAYOUTS.get(layout, build_price_list_xlsx)(
        price_type, warehouse, in_stock_only
    )
    filename = f"price-list-{timezone.localdate().strftime('%Y-%m-%d')}.xlsx"
    subject = f"Прайс-лист «{price_type.name}» — Автомеханика-Сибирь"
    body = (
        f"Во вложении — прайс-лист «{price_type.name}».\n"
        f"Склад: {warehouse.name}.\n"
        f"Дата формирования: {timezone.localdate().strftime('%d.%m.%Y')}.\n"
    )
    msg = EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=list(recipients),
    )
    msg.attach(filename, data, XLSX_CONTENT_TYPE)
    msg.send()
