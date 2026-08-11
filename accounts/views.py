import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from warehouses.models import Warehouse

from .emails import send_registration_request
from .forms import RegistrationRequestForm

logger = logging.getLogger(__name__)


def register(request):
    """Self-registration is disabled — show manager contacts plus a request form
    that is emailed to sales."""
    warehouses = Warehouse.objects.filter(is_active=True).order_by("name")
    if request.method == "POST":
        form = RegistrationRequestForm(request.POST)
        if form.is_valid():
            # Skip sending on a filled honeypot, but act as if it succeeded.
            if not form.cleaned_data.get("website"):
                try:
                    send_registration_request(
                        form.cleaned_data["company_name"],
                        form.cleaned_data["inn"],
                        form.cleaned_data["email"],
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("Registration request email failed")
                    messages.error(
                        request,
                        "Не удалось отправить заявку. Попробуйте позже "
                        "или позвоните менеджеру.",
                    )
                    return render(
                        request,
                        "registration/register.html",
                        {"warehouses": warehouses, "form": form},
                    )
            messages.success(
                request,
                "Спасибо! Ваша заявка отправлена — менеджер свяжется с вами.",
            )
            return redirect("register")
    else:
        form = RegistrationRequestForm()
    return render(
        request,
        "registration/register.html",
        {"warehouses": warehouses, "form": form},
    )


@login_required
def profile(request):
    return render(request, "accounts/profile.html")
