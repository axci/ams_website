"""Import external sales statistics from the 1C «Ведомость по товарам» .xlsx.

The report has a three-level hierarchy in the first column (outline levels):

    level 0  Product   — column D (Номенклатура.Код) is the sku
    level 1  Warehouse — column A is the warehouse name
    level 2  Document  — column A is the document; only «Расходная накладная»
             and «Корректировка реализации» are kept. For these rows:
                 column B = date (Документ движения.Дата)
                 column D = client (Документ движения.Контрагент)
                 column C = counterparty type
                 column G = quantity (расход)

Warehouses are mapped to the site's warehouses by name; rows at transit or
otherwise unmapped warehouses are skipped. Rows are matched to a Product by sku
(kept even when the sku is not in the catalog). Re-importing updates existing
rows, keyed by (warehouse, sku, document), instead of duplicating.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

import openpyxl
from django.db import transaction
from django.utils import timezone

from catalog.models import Product
from warehouses.models import Warehouse

from .models import SalesRecord

DOC_TYPES = ("Расходная накладная", "Корректировка реализации")

# Excel warehouse name → site warehouse name.
WAREHOUSE_MAP = {
    "Оптовый Кемерово (АМС)": "Кемерово",
    "Новокузнецк (АМС)": "Новокузнецк",
    "Склад Новосибирск (АМС)": "Новосибирск",
}

# Column indexes (1-based) — meaning depends on the hierarchy level.
COL_A, COL_DATE, COL_TYPE, COL_D, COL_RASHOD = 1, 2, 3, 4, 7


@dataclass
class SalesImportResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0          # rows at unmapped warehouses / missing sku
    unmatched_sku: int = 0    # imported, but the sku is not in the catalog
    errors: list = field(default_factory=list)  # list[(row_number, message)]


def _parse_date(value):
    if isinstance(value, datetime):
        dt = value
    elif value is None or str(value).strip() == "":
        return None
    else:
        s = str(value).strip()
        dt = None
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _qty(value):
    if value is None or str(value).strip() == "":
        return Decimal("0")
    try:
        return Decimal(str(value).replace(",", ".").strip())
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _cell(ws, r, c):
    v = ws.cell(r, c).value
    return str(v).strip() if v is not None else ""


def import_sales(file_obj):
    wb = openpyxl.load_workbook(file_obj, data_only=True)
    ws = wb.active
    result = SalesImportResult()

    site_wh = {w.name: w for w in Warehouse.objects.all()}
    target_wh = {xl: site_wh.get(name) for xl, name in WAREHOUSE_MAP.items()}
    products = {p.sku: p for p in Product.objects.all()}

    cur_sku = None
    cur_wh_excel = None
    seen = set()  # (warehouse_id, sku, document) already written this run

    with transaction.atomic():
        for r in range(1, ws.max_row + 1):
            a = _cell(ws, r, COL_A)
            if not a:
                continue
            level = ws.row_dimensions[r].outline_level if r in ws.row_dimensions else 0

            if level == 0:
                # Product group header — column D holds the sku. Header rows of
                # the report also land here but are harmless (overwritten before
                # any document row is reached).
                cur_sku = _cell(ws, r, COL_D)
                cur_wh_excel = None
            elif level == 1:
                cur_wh_excel = a
            elif level == 2:
                if not a.startswith(DOC_TYPES):
                    continue
                warehouse = target_wh.get(cur_wh_excel)
                if warehouse is None or not cur_sku:
                    result.skipped += 1
                    continue
                key = (warehouse.pk, cur_sku, a)
                if key in seen:
                    continue
                seen.add(key)
                product = products.get(cur_sku)
                if product is None:
                    result.unmatched_sku += 1
                doc_type = (
                    "Корректировка реализации"
                    if a.startswith("Корректировка")
                    else "Расходная накладная"
                )
                try:
                    _, created = SalesRecord.objects.update_or_create(
                        warehouse=warehouse,
                        sku=cur_sku,
                        document=a,
                        defaults={
                            "date": _parse_date(ws.cell(r, COL_DATE).value),
                            "product": product,
                            "client": _cell(ws, r, COL_D),
                            "client_type": _cell(ws, r, COL_TYPE),
                            "quantity": _qty(ws.cell(r, COL_RASHOD).value),
                            "document_type": doc_type,
                        },
                    )
                    result.created += 1 if created else 0
                    result.updated += 0 if created else 1
                except Exception as exc:  # noqa: BLE001 — report per row, keep going
                    result.errors.append((r, f"{cur_sku}: {exc}"))

    return result
