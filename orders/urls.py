from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("cart/", views.cart_detail, name="cart"),
    path("cart/add/<int:product_id>/", views.add_to_cart, name="add_to_cart"),
    path(
        "cart/item/<int:item_id>/update/",
        views.update_cart_item,
        name="update_cart_item",
    ),
    path(
        "cart/item/<int:item_id>/remove/",
        views.remove_from_cart,
        name="remove_from_cart",
    ),
    path("checkout/", views.checkout, name="checkout"),
    path("favorites/", views.wishlist, name="wishlist"),
    path(
        "favorites/toggle/<int:product_id>/",
        views.toggle_favorite,
        name="toggle_favorite",
    ),
    path("orders/", views.order_list, name="order_list"),
    path("orders/<int:pk>/", views.order_detail, name="order_detail"),
    path("orders/<int:pk>/invoice/", views.order_invoice, name="order_invoice"),
]
