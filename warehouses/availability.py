"""Stock availability across warehouses.

A buyer can order from their own warehouse(s) immediately, and from every other
warehouse with a 7-day delivery. So availability for ordering is the total stock
across all active warehouses, while the display distinguishes "own" from "other".
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


def available_map(product_ids):
    """Map product_id -> total available quantity across active warehouses."""
    rows = (
        Stock.objects.filter(product_id__in=list(product_ids), warehouse__is_active=True)
        .values("product_id")
        .annotate(total=Sum("quantity"))
    )
    return {r["product_id"]: r["total"] or 0 for r in rows}
