from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

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
