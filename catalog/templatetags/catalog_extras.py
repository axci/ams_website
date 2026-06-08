from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import template

register = template.Library()

CURRENCY = "₽"
NBSP = chr(0xA0)  # non-breaking space, keeps "3 361,52 ₽" from wrapping


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
