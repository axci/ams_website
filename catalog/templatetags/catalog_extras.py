from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import template
from django.utils.html import format_html

register = template.Library()

CURRENCY = "₽"
NBSP = chr(0xA0)  # non-breaking space, keeps "3 361,52 ₽" from wrapping


@register.simple_tag(takes_context=True)
def stock_badge(context, quantity):
    """Availability badge for a stock quantity.

    Buyers whose ``show_stock`` flag is on see the exact count; everyone else
    sees a fuzzy indicator: «только N» (<5, red), «мало» (5–10, yellow) or
    «много» (>10, green). Zero is always shown as out of stock.
    """
    try:
        qty = int(quantity or 0)
    except (TypeError, ValueError):
        qty = 0

    user = context.get("user") or getattr(context.get("request"), "user", None)
    exact = bool(
        user is not None
        and getattr(user, "is_authenticated", False)
        and getattr(user, "show_stock", False)
    )

    if qty <= 0:
        css, label = "text-bg-secondary", "Нет в наличии"
    elif exact:
        css, label = "text-bg-success", f"В наличии: {qty}"
    elif qty < 5:
        css, label = "text-bg-danger", f"только {qty}"
    elif qty <= 10:
        css, label = "text-bg-warning", "мало"
    else:
        css, label = "text-bg-success", "много"

    return format_html('<span class="badge {}">{}</span>', css, label)


@register.filter
def rubles(value):
    """Format a monetary amount as ``3 361,52 ₽`` (space thousands, comma decimal)."""
    if value is None or value == "":
        return ""
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return value

    sign = "-" if amount < 0 else ""
    integer_part, frac_part = f"{abs(amount):.2f}".split(".")
    grouped = f"{int(integer_part):,}".replace(",", NBSP)
    return f"{sign}{grouped},{frac_part}{NBSP}{CURRENCY}"
