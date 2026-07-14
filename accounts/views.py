from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from warehouses.models import Warehouse


def register(request):
    """Self-registration is disabled — direct visitors to a warehouse manager."""
    warehouses = Warehouse.objects.filter(is_active=True).order_by("name")
    return render(request, "registration/register.html", {"warehouses": warehouses})


@login_required
def profile(request):
    return render(request, "accounts/profile.html")
