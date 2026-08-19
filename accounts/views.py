import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordChangeView
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import redirect, render
from django.urls import reverse_lazy

from warehouses.models import Warehouse

from .emails import send_registration_request
from .forms import PasswordChangeForm, RegistrationRequestForm
from .models import RegistrationRequest

logger = logging.getLogger(__name__)


def register(request):
    """Self-registration is disabled — show manager contacts plus a request form
    that is emailed to sales."""
    warehouses = Warehouse.objects.filter(is_active=True).order_by("name")
    if request.method == "POST":
        form = RegistrationRequestForm(request.POST)
        if form.is_valid():
            # Skip storing/sending on a filled honeypot, but act as if it succeeded.
            if not form.cleaned_data.get("website"):
                # Store the request first so it is never lost, then notify sales
                # (best effort — a mail failure must not drop a saved заявка).
                RegistrationRequest.objects.create(
                    company_name=form.cleaned_data["company_name"],
                    inn=form.cleaned_data["inn"],
                    email=form.cleaned_data["email"],
                )
                try:
                    send_registration_request(
                        form.cleaned_data["company_name"],
                        form.cleaned_data["inn"],
                        form.cleaned_data["email"],
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("Registration request notification email failed")
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


class ChangePasswordView(SuccessMessageMixin, PasswordChangeView):
    """Self-service password change (login-required). Keeps the user signed in
    and returns to the profile with a success message."""

    form_class = PasswordChangeForm
    template_name = "accounts/change_password.html"
    success_url = reverse_lazy("profile")
    success_message = "Пароль успешно изменён."
