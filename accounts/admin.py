from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "username",
        "code",
        "email",
        "company_name",
        "type",
        "debt",
        "is_staff",
        "is_active",
    )
    search_fields = (
        "username",
        "email",
        "company_name",
        "first_name",
        "last_name",
        "code",
        "inn",
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
                    "address",
                    "debt",
                    "company_name",
                    "phone",
                    "manager",
                    "warehouses",
                )
            },
        ),
    )
