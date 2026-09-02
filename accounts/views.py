import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordChangeView
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Sum
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils import timezone

from orders.models import Order
from warehouses.models import Manager, Warehouse

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


@login_required
def manager_dashboard(request):
    """A manager's workspace: their clients, those clients' orders and sales
    stats. Managers see only their own clients; staff/superusers may view any
    manager (via ?manager=<id>)."""
    own = request.user.manager_profile
    if own is not None:
        # A manager is scoped to their own clients — other managers are never
        # available to them (no switcher, and any ?manager override is ignored),
        # even if the account also has staff access.
        manager = own
        can_view_all = False
        all_managers = None
    elif request.user.is_staff or request.user.is_superuser:
        # An admin without a manager profile may view any manager.
        can_view_all = True
        all_managers = Manager.objects.all()
        picked = request.GET.get("manager")
        manager = Manager.objects.filter(pk=picked).first() if picked else None
    else:
        raise PermissionDenied

    # Staff with no manager chosen yet — show the picker.
    if manager is None:
        return render(
            request,
            "accounts/manager_dashboard.html",
            {"manager": None, "all_managers": all_managers, "can_view_all": True},
        )

    clients = list(manager.clients.prefetch_related("companies").order_by("username"))
    orders = Order.objects.filter(user__manager=manager)
    active = orders.exclude(status=Order.Status.CANCELLED)

    # Per-client order count and sales (cancelled excluded).
    agg = {
        row["user"]: row
        for row in active.values("user").annotate(n=Count("id"), sales=Sum("total"))
    }
    for client in clients:
        row = agg.get(client.pk)
        client.orders_count = row["n"] if row else 0
        client.sales_total = row["sales"] if row else 0
        client.debt = client.total_debt()

    month_start = timezone.now().replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    stats = {
        "clients": len(clients),
        "orders": active.count(),
        "sales": active.aggregate(s=Sum("total"))["s"] or 0,
        "month_sales": active.filter(created_at__gte=month_start).aggregate(
            s=Sum("total")
        )["s"]
        or 0,
    }
    recent_orders = list(
        orders.select_related("user", "company", "warehouse").order_by("-created_at")[
            :20
        ]
    )

    return render(
        request,
        "accounts/manager_dashboard.html",
        {
            "manager": manager,
            "clients": clients,
            "stats": stats,
            "recent_orders": recent_orders,
            "all_managers": all_managers,
            "can_view_all": can_view_all,
        },
    )


class ChangePasswordView(SuccessMessageMixin, PasswordChangeView):
    """Self-service password change (login-required). Keeps the user signed in
    and returns to the profile with a success message."""

    form_class = PasswordChangeForm
    template_name = "accounts/change_password.html"
    success_url = reverse_lazy("profile")
    success_message = "Пароль успешно изменён."
