from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.shortcuts import redirect, render
from django.urls import path

from .imports import import_companies
from .models import Company, DeliveryAddress, User


class CompanyInline(admin.TabularInline):
    model = Company
    extra = 0
    fields = ("code", "company_name", "type", "inn", "kpp", "address", "phone", "debt")


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
    inlines = [CompanyInline, DeliveryAddressInline]
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
    list_display = ("code", "company_name", "type", "inn", "kpp", "debt", "user")
    list_filter = ("type",)
    search_fields = ("code", "company_name", "inn", "kpp")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)

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
