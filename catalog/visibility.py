"""Which brands a viewer may see, based on the warehouses they hold.

Brand.hidden_warehouses lists the warehouses a brand is hidden at. Empty — the
default, and true of most brands — means it is hidden nowhere and everyone sees
it. Otherwise a viewer sees the brand only if they hold at least one warehouse
it is not hidden at: a buyer with only Новосибирск loses a brand hidden there,
while a buyer with Новосибирск and Кемерово keeps it. Guests hold no warehouses
and so only ever see brands that are hidden nowhere.
"""

from django.db.models import Exists, OuterRef, Q

from .models import Brand


def _rule(brand_ref, warehouse_ids):
    """Brands hidden nowhere, plus those not hidden at one of `warehouse_ids`.

    Deliberately EXISTS subqueries rather than joins on the m2m: a join would
    match several rows per product and inflate the stock Sum annotations. That
    is one subquery per warehouse the viewer holds, which is a handful at most.
    """
    hidden = Brand.hidden_warehouses.through.objects.filter(
        brand_id=OuterRef(brand_ref)
    )
    q = Q(~Exists(hidden))
    for warehouse_id in sorted(warehouse_ids):
        q |= Q(~Exists(hidden.filter(warehouse_id=warehouse_id)))
    return q


def visible_brands_q(warehouse_ids):
    """Q for Brand."""
    return _rule("pk", warehouse_ids)


def visible_products_q(warehouse_ids):
    """Q for Product: the same rule, applied through `brand`."""
    return _rule("brand_id", warehouse_ids)
