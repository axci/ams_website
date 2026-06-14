from django.urls import path

from . import views

app_name = "warehouses"

urlpatterns = [
    path("switch/", views.switch_warehouse, name="switch"),
    path("contacts/", views.contacts, name="contacts"),
    path("<int:pk>/", views.warehouse_detail, name="detail"),
]
