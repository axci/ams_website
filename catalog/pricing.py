"""Helpers for resolving which price type applies to a viewer."""

from .models import PriceType


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
