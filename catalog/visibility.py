"""Which brands a viewer may see, based on the warehouses they have.

A brand with no warehouses selected is visible everywhere — that is the default
and covers most brands. Once warehouses are chosen (Brand.warehouses in the
admin), the brand is shown to any user holding at least one of them, regardless
of which warehouse is currently selected. Guests have no warehouses and so only
ever see unrestricted brands.
"""

from django.db.models import Exists, OuterRef, Q

from .models import Brand


def _rule(brand_ref, warehouse_ids):
    """Unrestricted brands, plus those allowed for any of `warehouse_ids`.

    Deliberately EXISTS subqueries rather than joins on the m2m: a brand may
    allow several warehouses and a user may hold several, so a join would match
    more than one row per product — duplicating it and inflating the stock Sum
    annotations.
    """
    links = Brand.warehouses.through.objects.filter(brand_id=OuterRef(brand_ref))
    q = Q(~Exists(links))
    if warehouse_ids:
        q |= Q(Exists(links.filter(warehouse_id__in=warehouse_ids)))
    return q


def visible_brands_q(warehouse_ids):
    """Q for Brand."""
    return _rule("pk", warehouse_ids)


def visible_products_q(warehouse_ids):
    """Q for Product: the same rule, applied through `brand`."""
    return _rule("brand_id", warehouse_ids)
