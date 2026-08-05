"""Stock availability across warehouses.

A buyer can order only from their own warehouse(s); stock in other warehouses is
shown for reference (a 7-day delivery) but can't be added to the cart. So
``own_qty`` / :func:`own_available_map` drive ordering, while ``total_qty`` (from
:func:`annotate_availability`) drives the display.
"""

from django.db.models import Case, IntegerField, Sum, When
from django.db.models.functions import Coalesce

from .models import Stock, Warehouse


def own_warehouse_ids(user):
    """Ids of the warehouses a user can order from directly ('own')."""
    if not getattr(user, "is_authenticated", False):
        return set()
    return set(user.accessible_warehouses().values_list("id", flat=True))


def annotate_availability(products, own_ids):
    """Annotate a product queryset with:

    - ``own_qty``   — stock in the user's own warehouses (immediate)
    - ``total_qty`` — stock across all active warehouses (own + 7-day delivery)
    """
    own_ids = list(own_ids)
    return products.annotate(
        total_qty=Coalesce(
            Sum(
                Case(
                    When(stocks__warehouse__is_active=True, then="stocks__quantity"),
                    default=0,
                    output_field=IntegerField(),
                )
            ),
            0,
        ),
        own_qty=Coalesce(
            Sum(
                Case(
                    When(stocks__warehouse_id__in=own_ids, then="stocks__quantity"),
                    default=0,
                    output_field=IntegerField(),
                )
            ),
            0,
        ),
    )


def warehouse_breakdown(product, own_ids):
    """Per-warehouse stock rows for a product's detail page: the user's own
    warehouses always, plus any other warehouse that has stock. Own first."""
    qty_by_wh = {
        s.warehouse_id: s.quantity
        for s in Stock.objects.filter(product=product, warehouse__is_active=True)
    }
    rows = []
    for wh in Warehouse.objects.filter(is_active=True):
        qty = qty_by_wh.get(wh.id, 0)
        is_own = wh.id in own_ids
        if is_own or qty > 0:
            rows.append({"warehouse": wh, "qty": qty, "is_own": is_own})
    rows.sort(key=lambda r: (not r["is_own"], -r["qty"]))
    return rows


def own_available_map(user, product_ids):
    """Map product_id -> quantity in the user's own warehouses only.

    This is what ordering is limited to: stock in other warehouses (7-day
    delivery) is deliberately excluded.
    """
    own_ids = own_warehouse_ids(user)
    if not own_ids:
        return {}
    rows = (
        Stock.objects.filter(
            product_id__in=list(product_ids),
            warehouse_id__in=own_ids,
            warehouse__is_active=True,
        )
        .values("product_id")
        .annotate(total=Sum("quantity"))
    )
    return {r["product_id"]: r["total"] or 0 for r in rows}
