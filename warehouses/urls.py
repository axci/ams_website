from django.urls import path

from . import views

app_name = "warehouses"

urlpatterns = [
    path("switch/", views.switch_warehouse, name="switch"),
]
