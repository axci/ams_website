from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Warehouse
from .selection import set_current_warehouse


@login_required
@require_POST
def switch_warehouse(request):
    warehouse = set_current_warehouse(request, request.POST.get("warehouse_id"))
    if warehouse:
        messages.success(request, f"Показаны остатки склада {warehouse.name}.")
    else:
        messages.error(request, "У вас нет доступа к этому складу.")
    return redirect(request.POST.get("next") or "catalog:product_list")


def contacts(request):
    # Fixed display order for this page; any other warehouses follow alphabetically.
    preferred = {"Новосибирск": 0, "Кемерово": 1, "Новокузнецк": 2}
    warehouses = sorted(
        Warehouse.objects.filter(is_active=True).prefetch_related("managers"),
        key=lambda w: (preferred.get(w.name, len(preferred)), w.name),
    )
    return render(request, "warehouses/contacts.html", {"warehouses": warehouses})


def warehouse_detail(request, pk):
    warehouse = get_object_or_404(
        Warehouse.objects.prefetch_related("managers"), pk=pk, is_active=True
    )
    return render(
        request, "warehouses/warehouse_detail.html", {"warehouse": warehouse}
    )
