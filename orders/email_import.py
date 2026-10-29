"""Turn a client order spreadsheet (received by email) into site Orders.

The client («НК-Нефть») emails an .xlsx laid out like this::

    Код товара | Наименование товара | Точка продаж | К заказу
    Точка продаж: АЗС №25 … (10)                                 <- section start
    101Н0102327 | Ароматизатор … | АЗС №25 …            | 4      <- item line
    …
                | 10            |                      | 49      <- section subtotal

Each «Точка продаж: …» marker row starts a new section, which becomes one
Order. Item lines carry the client's own product code («Код товара», matched to
``Product.nkoil_code``) and a quantity («К заказу»). Rows whose code column is
empty are per-section subtotals / the grand total and are skipped.

This module is deliberately free of any IMAP code: :func:`parse_order_rows` is
pure and unit-testable, and :func:`create_orders_for_email` does the DB work.
The IMAP fetching lives in the ``import_email_orders`` management command.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal

import openpyxl
from django.conf import settings
from django.db import transaction

POINT_PREFIX = "Точка продаж:"
# Columns are located by these header labels, because the client's layout
# varies — e.g. one file is 4 columns with «К заказу» in column D, another is
# 9 columns with «К заказу» in column E (and a «Цена (закупка)» column in D).
CODE_HEADER = "Код товара"
NAME_HEADER = "Наименование товара"
QTY_HEADER = "К заказу"
# Fallback 0-based positions if a header row is missing (the original layout).
DEFAULT_COLS = {"code": 0, "name": 1, "qty": 3}
# A trailing position count the client appends to a point-of-sale name, e.g.
# "АЗС №25 … (10)" — the "(10)" is the number of lines, not part of the name.
_TRAILING_COUNT = re.compile(r"\s*\(\d+\)\s*$")


# --------------------------------------------------------------------------- #
# Parsing (pure — no database, no IMAP)
# --------------------------------------------------------------------------- #
@dataclass
class ParsedLine:
    code: str
    name: str
    quantity: int
    row: int  # 1-based source row, for error messages


@dataclass
class ParsedOrder:
    point_of_sale: str
    items: list = field(default_factory=list)


def _clean(value):
    """Normalise a cell to a trimmed string (numbers lose a trailing .0)."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _parse_qty(value):
    """Parse the «К заказу» cell to a positive int, or None if not usable."""
    text = _clean(value).replace(",", ".")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    rounded = int(round(number))
    return rounded if rounded > 0 else None


def _header_columns(cells):
    """Map code/name/qty to 0-based indices from a header row, falling back to
    the default layout for any label that isn't found."""
    labels = {i: _clean(c).lower() for i, c in enumerate(cells)}
    cols = dict(DEFAULT_COLS)
    for key, header in (("code", CODE_HEADER), ("name", NAME_HEADER), ("qty", QTY_HEADER)):
        for i, text in labels.items():
            if text == header.lower():
                cols[key] = i
                break
    return cols


def parse_order_rows(rows):
    """Turn an iterable of row value-tuples into a list of :class:`ParsedOrder`.

    Accepts any iterable of sequences (cell values, left to right), so it can be
    tested without a real workbook. Columns are located from the header row (see
    :func:`_header_columns`); the code column (col A) anchors section markers and
    subtotal rows in every layout seen. Sections with no item lines are dropped.
    """
    orders = []
    current = None
    cols = dict(DEFAULT_COLS)

    def at(cells, key):
        i = cols[key]
        return cells[i] if 0 <= i < len(cells) else None

    for idx, row in enumerate(rows, start=1):
        cells = list(row) if row is not None else []
        code = _clean(at(cells, "code"))

        if code == CODE_HEADER:
            cols = _header_columns(cells)  # lock column positions from the header
            continue
        if code.startswith(POINT_PREFIX):
            name = _TRAILING_COUNT.sub("", code[len(POINT_PREFIX):].strip()).strip()
            current = ParsedOrder(point_of_sale=name)
            orders.append(current)
            continue
        if not code:
            continue  # subtotal / grand-total row (code column empty)

        # An item line. Tolerate items that appear before any marker row.
        if current is None:
            current = ParsedOrder(point_of_sale="")
            orders.append(current)
        current.items.append(
            ParsedLine(
                code=code,
                name=_clean(at(cells, "name")),
                quantity=_parse_qty(at(cells, "qty")) or 0,
                row=idx,
            )
        )

    return [order for order in orders if order.items]


def parse_order_workbook(path_or_file):
    """Parse the first sheet of an .xlsx (path or file-like) into ParsedOrders."""
    wb = openpyxl.load_workbook(path_or_file, data_only=True, read_only=True)
    try:
        ws = wb.worksheets[0]
        return parse_order_rows(ws.iter_rows(values_only=True))
    finally:
        wb.close()


# --------------------------------------------------------------------------- #
# Configuration / resolution helpers
# --------------------------------------------------------------------------- #
def get_config():
    """The EMAIL_ORDER_IMPORT settings dict (empty dict if unset)."""
    return getattr(settings, "EMAIL_ORDER_IMPORT", {}) or {}


def _parse_sender_map(raw):
    """Parse "a@b=login1,c@d=login2" into {email: login} (lower-cased emails)."""
    mapping = {}
    for pair in (raw or "").split(","):
        pair = pair.strip()
        if "=" not in pair:
            continue
        email_addr, _, login = pair.partition("=")
        email_addr, login = email_addr.strip().lower(), login.strip()
        if email_addr and login:
            mapping[email_addr] = login
    return mapping


def resolve_user(sender, config=None):
    """Find the site account an email's orders belong to.

    Resolution is by the explicit ORDER_SENDER_USER_MAP (sender → login) only —
    never by matching the sender to an account's email. Returns None when the
    sender is not mapped (or its mapped login does not exist), so unmapped mail
    is reported and left for a human rather than guessed at.
    """
    from accounts.models import User

    config = config or get_config()
    sender = (sender or "").strip().lower()
    if not sender:
        return None
    login = _parse_sender_map(config.get("SENDER_USER_MAP", "")).get(sender)
    if not login:
        return None
    return User.objects.filter(username=login).first()


def resolve_warehouse(config=None):
    """The default warehouse new imported orders are placed on."""
    from warehouses.models import Warehouse

    config = config or get_config()
    name = (config.get("DEFAULT_WAREHOUSE") or "").strip()
    if not name:
        return None
    return Warehouse.objects.filter(name=name).first()


def match_product(code):
    """Find a catalog product by the client's code (Product.nkoil_code)."""
    from catalog.models import Product

    code = (code or "").strip()
    if not code:
        return None
    qs = Product.objects.filter(nkoil_code=code)
    return qs.filter(is_active=True).first() or qs.first()


# --------------------------------------------------------------------------- #
# Order creation
# --------------------------------------------------------------------------- #
@dataclass
class ImportResult:
    created_orders: list = field(default_factory=list)   # Order pks
    sections: int = 0
    lines: int = 0
    matched: int = 0
    unmatched: list = field(default_factory=list)        # (code, name, qty, row)
    skipped: list = field(default_factory=list)          # bad/zero qty lines
    notes: list = field(default_factory=list)

    def summary(self):
        return (
            f"секций: {self.sections}, заказов создано: {len(self.created_orders)}, "
            f"строк: {self.lines}, сопоставлено: {self.matched}, "
            f"не найдено: {len(self.unmatched)}, пропущено: {len(self.skipped)}"
        )

    def render_report(self):
        """A human-readable report stored on the ImportedOrderEmail row."""
        lines = [self.summary()]
        pks = [pk for pk in self.created_orders if pk is not None]
        if pks:
            lines.append("Заказы: " + ", ".join(f"№{pk}" for pk in pks))
        for code, name, qty, row in self.unmatched:
            lines.append(f"НЕ НАЙДЕН товар [стр.{row}]: {code} ×{qty} — {name}")
        for code, name, qty, row in self.skipped:
            lines.append(f"ПРОПУЩЕНО (нет кол-ва) [стр.{row}]: {code} — {name}")
        lines.extend(self.notes)
        return "\n".join(lines)


def _order_comment(source_label, point_of_sale):
    parts = ["Импортирован из письма"]
    if source_label:
        parts[0] += f" ({source_label})"
    if point_of_sale:
        parts.append(f"Точка продаж: {point_of_sale}")
    return "\n".join(parts)


def create_orders_for_email(
    sections, *, user, warehouse, source_email=None, source_label="", dry_run=False
):
    """Create one pending Order per section for ``user`` on ``warehouse``.

    Lines are matched to products by the client code; unmatched or quantity-less
    lines are recorded in the result rather than failing the import. A section
    that yields no matched line creates no order. With ``dry_run`` nothing is
    written — the result reports what would happen. Everything is wrapped in one
    transaction so a failure leaves no partial import.
    """
    from .models import Order, OrderItem

    result = ImportResult(sections=len(sections))

    # A B2B buyer usually has exactly one company — attach it so the 1С export
    # resolves the контрагент; leave it unset when ambiguous.
    companies = list(user.companies.all()[:2])
    company = companies[0] if len(companies) == 1 else None

    with transaction.atomic():
        for section in sections:
            matched_lines = []
            for line in section.items:
                result.lines += 1
                if line.quantity <= 0:
                    result.skipped.append((line.code, line.name, line.quantity, line.row))
                    continue
                product = match_product(line.code)
                if product is None:
                    result.unmatched.append((line.code, line.name, line.quantity, line.row))
                    continue
                price = product.price_for_user(user)
                if price is None:
                    price = Decimal("0")
                    result.notes.append(
                        f"нет цены: {product.sku} ({line.code}) — цена 0"
                    )
                matched_lines.append((product, price, line.quantity))
                result.matched += 1

            if not matched_lines:
                continue  # don't create an empty order

            if dry_run:
                # Represent a would-be order without touching the DB.
                result.created_orders.append(None)
                continue

            order = Order.objects.create(
                user=user,
                warehouse=warehouse,
                company=company,
                status=Order.Status.PENDING,
                comment=_order_comment(source_label, section.point_of_sale),
                imported_from_email=source_email,
            )
            for product, price, quantity in matched_lines:
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    sku=product.sku,
                    name=product.name,
                    price=price,
                    quantity=quantity,
                )
            order.recalculate_total()
            result.created_orders.append(order.pk)

        if dry_run:
            transaction.set_rollback(True)

    return result
