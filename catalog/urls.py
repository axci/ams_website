from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("", views.product_list, name="product_list"),
    path("search/suggest/", views.search_suggest, name="search_suggest"),
    path("price.xlsx", views.product_price_xlsx, name="price_xlsx"),
    path("product/<int:pk>/", views.product_detail, name="product_detail"),
]
