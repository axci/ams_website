from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.shortcuts import redirect, render
from django.urls import path

from .imports import import_users
from .models import User


class UserImportForm(forms.Form):
    file = forms.FileField(label="Excel-файл (.xlsx)")


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    change_list_template = "admin/accounts/user/change_list.html"
    list_display = (
        "username",
        "code",
        "email",
        "company_name",
        "type",
        "price_type",
        "debt",
        "is_staff",
        "is_active",
    )
    list_filter = BaseUserAdmin.list_filter + ("price_type", "show_stock")
    search_fields = (
        "username",
        "email",
        "company_name",
        "first_name",
        "last_name",
        "code",
        "inn",
        "kpp",
    )
    filter_horizontal = BaseUserAdmin.filter_horizontal + ("warehouses",)
    autocomplete_fields = ("manager",)
    fieldsets = BaseUserAdmin.fieldsets + (
        (
            "Buyer info",
            {
                "fields": (
                    "code",
                    "type",
                    "inn",
                    "kpp",
                    "address",
                    "debt",
                    "company_name",
                    "phone",
                    "manager",
                    "price_type",
                    "show_stock",
                    "warehouses",
                )
            },
        ),
    )

    def get_urls(self):
        custom = [
            path(
                "import-excel/",
                self.admin_site.admin_view(self.import_excel),
                name="accounts_user_import_excel",
            ),
        ]
        return custom + super().get_urls()

    def import_excel(self, request):
        if request.method == "POST":
            form = UserImportForm(request.POST, request.FILES)
            if form.is_valid():
                result = import_users(form.cleaned_data["file"])
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
                return redirect("admin:accounts_user_changelist")
        else:
            form = UserImportForm()
        context = {
            **self.admin_site.each_context(request),
            "title": "Импорт пользователей из Excel",
            "form": form,
            "opts": self.model._meta,
        }
        return render(request, "admin/accounts/user/import_excel.html", context)
