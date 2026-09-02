"""Import products (and per-warehouse stock) from an .xlsx workbook.

The first row is the header. Recognised product columns (case-insensitive):

    sku, article, name, category, subcategory, model product (model_product),
    weight, volume, viscosity, description (описание),
    pack quantity (количество штук в упаковке),
    manufacturer number (manufacturer_number), price, brand,
    certificate (сертификат соответствия — a link or text)

A header that matches a price type name («Розничные», «Крупный ОПТ», …) fills
that type's per-product price. Columns the catalog export adds for information
only (see IGNORED_COLUMNS) are skipped. Any other non-empty header is treated
as a WAREHOUSE name, and that column's cells as the stock quantity for that
warehouse. Rows are matched/created by ``sku``. Categories, subcategories,
models, brands and warehouses are matched case-insensitively (Unicode-aware)
and created on demand.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

import openpyxl
from django.db import transaction
from django.utils.text import slugify

from warehouses.models import Stock, Warehouse

from .models import (
    Brand,
    Category,
    ModelProduct,
    PriceType,
    Product,
    ProductPrice,
    SubCategory,
)

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
    "weight unit": "weight_unit",
    "weight_unit": "weight_unit",
    "weight_m": "weight_unit",
    "единица веса": "weight_unit",
    "volume": "volume",
    "volume unit": "volume_unit",
    "volume_unit": "volume_unit",
    "volume_m": "volume_unit",
    "единица объёма": "volume_unit",
    "viscosity": "viscosity",
    "вязкость": "viscosity",
    "pack quantity": "pack_quantity",
    "pack_quantity": "pack_quantity",
    "pack": "pack_quantity",
    "количество штук в упаковке": "pack_quantity",
    "штук в упаковке": "pack_quantity",
    "кол-во в упаковке": "pack_quantity",
    "количество в упаковке": "pack_quantity",
    "упаковка": "pack_quantity",
    "description": "description",
    "описание": "description",
    "manufacturer number": "manufacturer_number",
    "manufacturer_number": "manufacturer_number",
    "mann_cross": "mann_cross",
    "mann cross": "mann_cross",
    "mann": "mann_cross",
    "mahl_cross": "mahl_cross",
    "mahle_cross": "mahl_cross",
    "mahl cross": "mahl_cross",
    "mahle cross": "mahl_cross",
    "mahle": "mahl_cross",
    "sakura_cross": "sakura_cross",
    "sakura cross": "sakura_cross",
    "sakura": "sakura_cross",
    "knecht_cross": "knecht_cross",
    "knecht cross": "knecht_cross",
    "knecht": "knecht_cross",
    "oem_cross": "oem_cross",
    "oem cross": "oem_cross",
    "oem": "oem_cross",
    "certificate": "certificate",
    "сертификат": "certificate",
    "сертификат соответствия": "certificate",
    "certificate of conformity": "certificate",
    "price": "price",
    "vat": "vat_rate",
    "vat_rate": "vat_rate",
    "ндс": "vat_rate",
    "ставка ндс": "vat_rate",
    "brand": "brand",
}

# Written by the catalog export for information only. Listed here so a
# round-tripped file does not mistake them for warehouse columns. The certificate
# file cannot be re-uploaded from a spreadsheet cell, so it is export-only.
IGNORED_COLUMNS = {
    "is_active", "slug", "picture", "certificate_file", "show_certificate",
    "created_at", "updated_at",
}

TEXT_LIMITS ={"sku": 64, "article": 64, "manufacturer_number": 64, "mann_cross": 255, "mahl_cross": 255, "sakura_cross": 255, "knecht_cross": 255, "oem_cross": 10000, "certificate": 500, "name": 200, "viscosity": 20, "weight_unit": 16, "volume_unit": 16}


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
        self.models = {
            (m.brand_id, m.name.casefold()): m for m in ModelProduct.objects.all()
        }
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

    def model(self, brand, name):
        """Find-or-create a model scoped to its brand (same name may exist
        under different brands)."""
        if not name:
            return None
        key = (brand.pk if brand else None, name.casefold())
        obj = self.models.get(key)
        if obj is None:
            obj = ModelProduct.objects.create(name=name[:200], brand=brand)
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

    # Columns named after a price type («Розничные», «Крупный ОПТ», …) fill
    # that type's per-product price; anything else unrecognised is a warehouse.
    price_types = {_norm(pt.name): pt for pt in PriceType.objects.all()}

    field_cols, warehouse_cols, price_type_cols = {}, {}, {}
    for idx, raw in enumerate(all_rows[0]):
        key = _norm(raw)
        if not key:
            continue
        if key in FIELD_ALIASES:
            field_cols[idx] = FIELD_ALIASES[key]
        elif key in IGNORED_COLUMNS:
            continue
        elif key in price_types:
            price_type_cols[idx] = price_types[key]
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
                resolver.model(brand, _text(values.get("model_product"), 200))
                if "model_product" in values
                else None
            )

            defaults = {"brand": brand}
            if "article" in values:
                defaults["article"] = _text(values.get("article"), 64)
            if "manufacturer_number" in values:
                defaults["manufacturer_number"] = _text(values.get("manufacturer_number"), 64)
            if "mann_cross" in values:
                defaults["mann_cross"] = _text(values.get("mann_cross"), 255)
            if "mahl_cross" in values:
                defaults["mahl_cross"] = _text(values.get("mahl_cross"), 255)
            if "sakura_cross" in values:
                defaults["sakura_cross"] = _text(values.get("sakura_cross"), 255)
            if "knecht_cross" in values:
                defaults["knecht_cross"] = _text(values.get("knecht_cross"), 255)
            if "oem_cross" in values:
                defaults["oem_cross"] = _text(values.get("oem_cross"), 10000)
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
            if "vat_rate" in values:
                d = _decimal(values.get("vat_rate"))
                if d is not None:
                    defaults["vat_rate"] = d
            if "weight" in values:
                defaults["weight"] = _decimal(values.get("weight"))
            if "weight_unit" in values:
                wu = _text(values.get("weight_unit"), 16)
                if wu:
                    defaults["weight_unit"] = wu
            if "volume" in values:
                defaults["volume"] = _decimal(values.get("volume"))
            if "volume_unit" in values:
                vu = _text(values.get("volume_unit"), 16)
                if vu:
                    defaults["volume_unit"] = vu
            if "pack_quantity" in values:
                defaults["pack_quantity"] = _int(values.get("pack_quantity"))
            if "viscosity" in values:
                defaults["viscosity"] = _viscosity(values.get("viscosity"))
            if "description" in values:
                defaults["description"] = _text(values.get("description"))
            if "certificate" in values:
                defaults["certificate"] = _text(values.get("certificate"), 500)

            # A new product needs a name even if the file omits the column.
            if "name" not in defaults and not Product.objects.filter(sku=sku).exists():
                defaults["name"] = sku

            with transaction.atomic():
                product, created = Product.objects.update_or_create(
                    sku=sku, defaults=defaults
                )
                result.created += 1 if created else 0
                result.updated += 0 if created else 1

                for i, price_type in price_type_cols.items():
                    d = _decimal(cell(i))
                    if d is None:
                        continue
                    ProductPrice.objects.update_or_create(
                        product=product, price_type=price_type, defaults={"price": d}
                    )

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
