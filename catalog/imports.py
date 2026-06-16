"""Import products (and per-warehouse stock) from an .xlsx workbook.

The first row is the header. Recognised product columns (case-insensitive):

    sku, article, name, category, subcategory, model product (model_product),
    weight, volume, manufacturer number (manufacturer_number), price, brand

Any other non-empty header is treated as a WAREHOUSE name, and that column's
cells as the stock quantity for that warehouse. Rows are matched/created by
``sku``. Categories, subcategories, models, brands and warehouses are matched
case-insensitively (Unicode-aware) and created on demand.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

import openpyxl
from django.db import transaction
from django.utils.text import slugify

from warehouses.models import Stock, Warehouse

from .models import Brand, Category, ModelProduct, Product, SubCategory

FIELD_ALIASES = {
    "sku": "sku",
    "article": "article",
    "name": "name",
    "category": "category",
    "subcategory": "subcategory",
    "sub category": "subcategory",
    "model product": "model_product",
    "model_product": "model_product",
    "model": "model_product",
    "weight": "weight",
    "volume": "volume",
    "viscosity": "viscosity",
    "вязкость": "viscosity",
    "manufacturer number": "manufacturer_number",
    "manufacturer_number": "manufacturer_number",
    "price": "price",
    "brand": "brand",
}

TEXT_LIMITS = {"sku": 64, "article": 64, "manufacturer_number": 64, "name": 200, "viscosity": 20}


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list = field(default_factory=list)  # list[(row_number, message)]
    warehouses: list = field(default_factory=list)


def _norm(value):
    return str(value).strip().lower() if value is not None else ""


def _text(value, limit=None):
    if value is None:
        return ""
    s = str(value).strip()
    return s[:limit] if limit else s


def _decimal(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        return Decimal(str(value).replace(",", ".").strip())
    except (InvalidOperation, ValueError):
        return None


def _int(value):
    d = _decimal(value)
    if d is None:
        return None
    try:
        return max(0, int(d))
    except (ValueError, TypeError):
        return None


_VISCOSITY_RE = re.compile(r"(\d{1,2})W[\s\-/]?(\d{1,3})", re.IGNORECASE)


def _viscosity(value):
    """Normalise a viscosity cell to a symbol-free grade, e.g. 5W-30 -> 5W30."""
    text = _text(value, 20)
    match = _VISCOSITY_RE.search(text)
    return f"{match.group(1)}W{match.group(2)}" if match else text


class _Resolver:
    """Find-or-create lookups with Unicode case-insensitive matching.

    SQLite's ``__iexact`` only case-folds ASCII, so Cyrillic names are matched
    here in Python via ``str.casefold()`` to avoid creating duplicates.
    """

    def __init__(self):
        self.brands = {b.name.casefold(): b for b in Brand.objects.all()}
        self.categories = {c.name.casefold(): c for c in Category.objects.all()}
        self.models = {m.name.casefold(): m for m in ModelProduct.objects.all()}
        self.subcats = {
            (s.category_id, s.name.casefold()): s for s in SubCategory.objects.all()
        }
        self.warehouses = {w.name.casefold(): w for w in Warehouse.objects.all()}

    def brand(self, name):
        if not name:
            return None
        key = name.casefold()
        obj = self.brands.get(key)
        if obj is None:
            obj = Brand.objects.create(name=name[:120])
            self.brands[key] = obj
        return obj

    def category(self, name):
        if not name:
            return None
        key = name.casefold()
        obj = self.categories.get(key)
        if obj is None:
            obj = Category.objects.create(name=name[:150])
            self.categories[key] = obj
        return obj

    def model(self, name):
        if not name:
            return None
        key = name.casefold()
        obj = self.models.get(key)
        if obj is None:
            obj = ModelProduct.objects.create(name=name[:200])
            self.models[key] = obj
        return obj

    def subcategory(self, category, name):
        if not (name and category):
            return None
        key = (category.pk, name.casefold())
        obj = self.subcats.get(key)
        if obj is None:
            obj = SubCategory.objects.create(category=category, name=name[:150])
            self.subcats[key] = obj
        return obj

    def warehouse(self, name):
        key = name.casefold()
        obj = self.warehouses.get(key)
        if obj is None:
            base = (slugify(name, allow_unicode=True) or "wh").upper()[:32]
            code, n = base, 1
            while Warehouse.objects.filter(code=code).exists():
                n += 1
                code = f"{base[:28]}-{n}"
            obj = Warehouse.objects.create(name=name, code=code)
            self.warehouses[key] = obj
        return obj


def import_products(file_obj, default_brand=None):
    wb = openpyxl.load_workbook(file_obj, data_only=True, read_only=True)
    ws = wb.active
    result = ImportResult()

    all_rows = list(ws.iter_rows(values_only=True))
    if not all_rows:
        result.errors.append((0, "The file is empty."))
        return result

    field_cols, warehouse_cols = {}, {}
    for idx, raw in enumerate(all_rows[0]):
        key = _norm(raw)
        if not key:
            continue
        if key in FIELD_ALIASES:
            field_cols[idx] = FIELD_ALIASES[key]
        else:
            warehouse_cols[idx] = str(raw).strip()

    if "sku" not in field_cols.values():
        result.errors.append((0, "No 'sku' column found in the header row."))
        return result

    resolver = _Resolver()
    warehouses = {i: resolver.warehouse(n) for i, n in warehouse_cols.items()}
    result.warehouses = sorted({w.name for w in warehouses.values()})

    for row_num, row in enumerate(all_rows[1:], start=2):
        if row is None or all(c is None or str(c).strip() == "" for c in row):
            continue

        def cell(i):
            return row[i] if i < len(row) else None

        values = {fkey: cell(i) for i, fkey in field_cols.items()}
        sku = _text(values.get("sku"), 64)
        if not sku:
            result.skipped += 1
            continue

        try:
            # Resolve taxonomy OUTSIDE the per-row savepoint so created lookups
            # survive (and stay cached) even if a later product row fails.
            brand = resolver.brand(_text(values.get("brand"), 120)) if "brand" in values else None
            if brand is None:
                brand = default_brand
            if brand is None:
                raise ValueError("no brand — choose a default brand for the upload")

            category = (
                resolver.category(_text(values.get("category"), 150))
                if "category" in values
                else None
            )
            subcategory = (
                resolver.subcategory(category, _text(values.get("subcategory"), 150))
                if "subcategory" in values
                else None
            )
            model_product = (
                resolver.model(_text(values.get("model_product"), 200))
                if "model_product" in values
                else None
            )

            defaults = {"brand": brand}
            if "article" in values:
                defaults["article"] = _text(values.get("article"), 64)
            if "manufacturer_number" in values:
                defaults["manufacturer_number"] = _text(values.get("manufacturer_number"), 64)
            if "name" in values:
                defaults["name"] = _text(values.get("name"), 200) or sku
            if "category" in values:
                defaults["category"] = category
            if "subcategory" in values:
                defaults["subcategory"] = subcategory
            if "model_product" in values:
                defaults["model_product"] = model_product
            if "price" in values:
                d = _decimal(values.get("price"))
                defaults["price"] = d if d is not None else Decimal("0")
            if "weight" in values:
                defaults["weight"] = _decimal(values.get("weight"))
            if "volume" in values:
                defaults["volume"] = _decimal(values.get("volume"))
            if "viscosity" in values:
                defaults["viscosity"] = _viscosity(values.get("viscosity"))

            # A new product needs a name even if the file omits the column.
            if "name" not in defaults and not Product.objects.filter(sku=sku).exists():
                defaults["name"] = sku

            with transaction.atomic():
                product, created = Product.objects.update_or_create(
                    sku=sku, defaults=defaults
                )
                result.created += 1 if created else 0
                result.updated += 0 if created else 1

                for i, warehouse in warehouses.items():
                    qty = _int(cell(i))
                    if qty is None:
                        continue
                    Stock.objects.update_or_create(
                        product=product, warehouse=warehouse, defaults={"quantity": qty}
                    )
        except Exception as exc:  # noqa: BLE001 — report per row, keep importing
            result.errors.append((row_num, f"{sku or '(no sku)'}: {exc}"))

    return result
