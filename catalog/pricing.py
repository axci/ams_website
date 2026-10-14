"""Helpers for resolving which price type applies to a viewer."""

from decimal import Decimal

from .models import PriceType


def _is_authed(user):
    return user is not None and getattr(user, "is_authenticated", False)


def brand_discounts_for_user(user):
    """Map ``{brand_id: percent}`` of the best brand discount available to a
    user across all of their companies. Empty for guests or when none apply."""
    if not _is_authed(user):
        return {}
    from accounts.models import CompanyBrandDiscount

    best = {}
    for brand_id, percent in CompanyBrandDiscount.objects.filter(
        company__users=user, percent__gt=0
    ).values_list("brand_id", "percent"):
        if brand_id is not None and percent > best.get(brand_id, 0):
            best[brand_id] = percent
    return best


def brand_discount_percent(user, brand_id):
    """Best discount percent a user gets on a single brand (``Decimal('0')``
    when none)."""
    if not brand_id or not _is_authed(user):
        return Decimal("0")
    from accounts.models import CompanyBrandDiscount

    best = (
        CompanyBrandDiscount.objects.filter(
            company__users=user, brand_id=brand_id, percent__gt=0
        )
        .order_by("-percent")
        .values_list("percent", flat=True)
        .first()
    )
    return best or Decimal("0")


def price_type_for_user(user):
    """Return the PriceType a user should see.

    Guests (anonymous or ``None``) get the public type («Розничные»).
    Authenticated buyers get their own ``price_type`` or, if unset, the
    default buyer type («Крупный ОПТ»).
    """
    if user is not None and getattr(user, "is_authenticated", False):
        return user.price_type or PriceType.default_type()
    return PriceType.public_type()


def price_type_for_request(request):
    return price_type_for_user(getattr(request, "user", None))
