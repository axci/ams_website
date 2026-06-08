from .selection import get_accessible_warehouses, get_current_warehouse


def warehouse_context(request):
    """Expose the current/accessible warehouses to every template."""
    if not getattr(request.user, "is_authenticated", False):
        return {}
    return {
        "current_warehouse": get_current_warehouse(request),
        "accessible_warehouses": get_accessible_warehouses(request.user),
    }
