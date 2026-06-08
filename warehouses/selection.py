"""Helpers for the buyer's session-bound 'current warehouse'.

A buyer may have access to several warehouses but views one at a time. The
selected warehouse id is stored in the session and always validated against the
warehouses the user is actually allowed to see.
"""

from .models import Warehouse

SESSION_KEY = "current_warehouse_id"


def get_accessible_warehouses(user):
    if not getattr(user, "is_authenticated", False):
        return Warehouse.objects.none()
    return user.accessible_warehouses()


def get_current_warehouse(request):
    """Return the user's current warehouse, defaulting to their first one."""
    user = request.user
    if not getattr(user, "is_authenticated", False):
        return None

    accessible = get_accessible_warehouses(user)
    warehouse_id = request.session.get(SESSION_KEY)
    if warehouse_id:
        warehouse = accessible.filter(pk=warehouse_id).first()
        if warehouse:
            return warehouse

    # Fall back to the first accessible warehouse and remember it.
    warehouse = accessible.first()
    if warehouse:
        request.session[SESSION_KEY] = warehouse.pk
    return warehouse


def set_current_warehouse(request, warehouse_id):
    """Switch the current warehouse, only if the user may access it."""
    warehouse = get_accessible_warehouses(request.user).filter(pk=warehouse_id).first()
    if warehouse:
        request.session[SESSION_KEY] = warehouse.pk
    return warehouse
