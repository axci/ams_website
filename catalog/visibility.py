"""Which brands a viewer may see, based on their current warehouse.

A brand with no warehouses selected is visible everywhere — that is the default
and covers most brands. Once warehouses are chosen (Brand.warehouses in the
admin), the brand is only shown while viewing one of them, so a buyer whose
warehouse is not listed never sees it. Guests have no warehouse and therefore
only ever see unrestricted brands.
"""

from django.db.models import Q


def visible_brands_q(warehouse):
    """Q for Brand: unrestricted brands, plus those allowed for `warehouse`."""
    q = Q(warehouses__isnull=True)
    if warehouse is not None:
        q |= Q(warehouses=warehouse)
    return q


def visible_products_q(warehouse):
    """Q for Product: the same rule, applied through `brand`.

    Keep this inside a single .filter() call so the OR uses one join and cannot
    duplicate rows (which would inflate the stock Sum annotations).
    """
    q = Q(brand__warehouses__isnull=True)
    if warehouse is not None:
        q |= Q(brand__warehouses=warehouse)
    return q
