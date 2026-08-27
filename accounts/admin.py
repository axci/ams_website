import logging

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.html import format_html

from catalog.models import PriceType
from warehouses.models import Manager, Warehouse

from .emails import send_credentials
from .imports import import_companies
from .models import Company, DeliveryAddress, RegistrationRequest, User

logger = logging.getLogger(__name__)


class CompanyUsersInline(admin.TabularInline):
    """Link existing companies to a user (edit company details on the Company
    page). Companies are many-to-many with users, so this edits the join table."""

    model = Company.users.through
    extra = 0
    autocomplete_fields = ("company",)
    verbose_name = "компания"
    verbose_name_plural = "компании"


class DeliveryAddressInline(admin.TabularInline):
    model = DeliveryAddress
    extra = 0
    fields = ("label", "address")


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "username", "email", "company_list", "price_type", "is_staff", "is_active"
    )
    list_filter = BaseUserAdmin.list_filter + ("price_type", "show_stock")
    search_fields = (
        "username", "email", "first_name", "last_name",
        "companies__code", "companies__company_name", "companies__inn",
    )
    filter_horizontal = BaseUserAdmin.filter_horizontal + ("warehouses",)
    autocomplete_fields = ("manager",)
    inlines = [CompanyUsersInline, DeliveryAddressInline]
    fieldsets = BaseUserAdmin.fieldsets + (
        (
            "Настройки покупателя",
            {"fields": ("manager", "price_type", "show_stock", "free_delivery_min", "warehouses")},
        ),
    )

    @admin.display(description="Компании")
    def company_list(self, obj):
        names = [c.company_name or c.code or "—" for c in obj.companies.all()[:3]]
        return ", ".join(names) or "—"


class CompanyImportForm(forms.Form):
    file = forms.FileField(label="Excel-файл (.xlsx)")


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    change_list_template = "admin/accounts/company/change_list.html"
    list_display = ("code", "company_name", "type", "inn", "kpp", "debt", "user_list")
    list_filter = ("type",)
    search_fields = ("code", "company_name", "inn", "kpp")
    filter_horizontal = ("users",)

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("users")

    @admin.display(description="Аккаунты")
    def user_list(self, obj):
        users = list(obj.users.all())
        label = ", ".join(u.get_username() for u in users[:3]) or "—"
        if len(users) > 3:
            label += f" +{len(users) - 3}"
        return label

    def get_urls(self):
        custom = [
            path(
                "import-excel/",
                self.admin_site.admin_view(self.import_excel),
                name="accounts_company_import_excel",
            ),
        ]
        return custom + super().get_urls()

    def import_excel(self, request):
        if request.method == "POST":
            form = CompanyImportForm(request.POST, request.FILES)
            if form.is_valid():
                result = import_companies(form.cleaned_data["file"])
                self.message_user(
                    request,
                    f"Импорт завершён: создано {result.created}, "
                    f"обновлено {result.updated}, пропущено {result.skipped}, "
                    f"ошибок {len(result.errors)}.",
                    level=messages.SUCCESS if not result.errors else messages.WARNING,
                )
                for row_num, msg in result.errors[:15]:
                    self.message_user(
                        request, f"Строка {row_num}: {msg}", messages.ERROR
                    )
                if len(result.errors) > 15:
                    self.message_user(
                        request,
                        f"…и ещё {len(result.errors) - 15} строк(и) с ошибками.",
                        messages.ERROR,
                    )
                return redirect("admin:accounts_company_changelist")
        else:
            form = CompanyImportForm()
        context = {
            **self.admin_site.each_context(request),
            "title": "Импорт компаний из Excel",
            "form": form,
            "opts": self.model._meta,
        }
        return render(request, "admin/accounts/company/import_excel.html", context)


@admin.register(DeliveryAddress)
class DeliveryAddressAdmin(admin.ModelAdmin):
    list_display = ("user", "label", "address")
    search_fields = ("label", "address", "user__username")
    autocomplete_fields = ("user",)


# Ambiguous look-alike characters left out so a client can read the password.
_PWD_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class CreateClientForm(forms.Form):
    """Fields the manager fills to turn a registration request into a real
    account. The password is emailed to the client, so it is shown in clear."""

    username = forms.CharField(label="Логин", max_length=150)
    first_name = forms.CharField(label="Имя", max_length=150, required=False)
    last_name = forms.CharField(label="Фамилия", max_length=150, required=False)
    email = forms.EmailField(label="Email")
    password = forms.CharField(label="Пароль", max_length=128)
    code = forms.CharField(label="Код компании", max_length=32, required=False)
    delivery_address = forms.CharField(
        label="Адрес доставки", max_length=255, required=False
    )
    warehouses = forms.ModelMultipleChoiceField(
        label="Склады",
        queryset=Warehouse.objects.filter(is_active=True),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    price_type = forms.ModelChoiceField(
        label="Тип цены", queryset=PriceType.objects.all(), required=False
    )
    manager = forms.ModelChoiceField(
        label="Менеджер", queryset=Manager.objects.all(), required=False
    )

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Пользователь с таким логином уже существует.")
        return username

    def clean_code(self):
        code = (self.cleaned_data.get("code") or "").strip()
        if code and Company.objects.filter(code=code).exists():
            raise forms.ValidationError("Компания с таким кодом уже существует.")
        return code

    def clean_password(self):
        password = self.cleaned_data["password"]
        try:
            validate_password(password)
        except DjangoValidationError as exc:
            raise forms.ValidationError(list(exc.messages))
        return password


@admin.register(RegistrationRequest)
class RegistrationRequestAdmin(admin.ModelAdmin):
    change_form_template = "admin/accounts/registrationrequest/change_form.html"
    list_display = (
        "company_name", "inn", "email", "status", "created_at", "action_link"
    )
    list_filter = ("status",)
    search_fields = ("company_name", "inn", "email")
    readonly_fields = ("created_at", "processed_at", "created_user")
    fields = (
        "company_name", "inn", "email", "status", "note",
        "created_user", "created_at", "processed_at",
    )
    ordering = ("-created_at",)

    @admin.display(description="Действие")
    def action_link(self, obj):
        if obj.created_user_id:
            return "Аккаунт создан"
        url = reverse("admin:accounts_registrationrequest_process", args=[obj.pk])
        return format_html('<a class="button" href="{}">Создать аккаунт</a>', url)

    def get_urls(self):
        custom = [
            path(
                "<int:pk>/process/",
                self.admin_site.admin_view(self.process_view),
                name="accounts_registrationrequest_process",
            ),
        ]
        return custom + super().get_urls()

    def process_view(self, request, pk):
        req = get_object_or_404(RegistrationRequest, pk=pk)
        change_url = reverse("admin:accounts_registrationrequest_change", args=[pk])
        if req.created_user_id:
            self.message_user(
                request, "По этой заявке уже создан аккаунт.", messages.WARNING
            )
            return redirect(change_url)

        if request.method == "POST":
            form = CreateClientForm(request.POST)
            if form.is_valid():
                data = form.cleaned_data
                with transaction.atomic():
                    user = User.objects.create_user(
                        username=data["username"],
                        email=data["email"],
                        password=data["password"],
                        first_name=data["first_name"],
                        last_name=data["last_name"],
                        price_type=data["price_type"],
                        manager=data["manager"],
                    )
                    if data["warehouses"]:
                        user.warehouses.set(data["warehouses"])
                    if req.company_name or req.inn or data["code"]:
                        company = Company.objects.create(
                            code=data["code"] or None,
                            company_name=req.company_name,
                            inn=req.inn or "",
                        )
                        company.users.add(user)
                    if data["delivery_address"]:
                        DeliveryAddress.objects.create(
                            user=user, address=data["delivery_address"]
                        )
                    req.status = RegistrationRequest.Status.PROCESSED
                    req.created_user = user
                    req.processed_at = timezone.now()
                    req.save(
                        update_fields=["status", "created_user", "processed_at"]
                    )
                # Send the credentials outside the transaction: a mail hiccup
                # must not roll back an account that already exists.
                name = user.get_full_name() or user.first_name
                try:
                    send_credentials(
                        user.email, name, user.username, data["password"]
                    )
                    self.message_user(
                        request,
                        f"Аккаунт «{user.username}» создан, письмо с доступами "
                        f"отправлено на {user.email}.",
                        messages.SUCCESS,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("Credentials email failed")
                    self.message_user(
                        request,
                        f"Аккаунт «{user.username}» создан, но письмо отправить "
                        "не удалось — сообщите доступы клиенту вручную "
                        f"(пароль: {data['password']}).",
                        messages.WARNING,
                    )
                return redirect(change_url)
        else:
            suggested_username = (req.email.split("@")[0] if req.email else "").strip()
            default_price_type = (
                PriceType.objects.filter(name__iexact="Крупный ОПТ").first()
                or PriceType.objects.filter(is_default=True).first()
            )
            form = CreateClientForm(
                initial={
                    "username": suggested_username,
                    "email": req.email,
                    "password": get_random_string(10, _PWD_ALPHABET),
                    "price_type": default_price_type,
                }
            )

        context = {
            **self.admin_site.each_context(request),
            "title": f"Создание аккаунта по заявке: {req.company_name}",
            "form": form,
            "req": req,
            "opts": self.model._meta,
        }
        return render(
            request, "admin/accounts/registrationrequest/process.html", context
        )
