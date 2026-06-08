from .utils import get_or_create_cart


def cart_context(request):
    """Expose the current user's cart to every template (for the navbar)."""
    if not getattr(request.user, "is_authenticated", False):
        return {}
    return {"nav_cart": get_or_create_cart(request.user)}
