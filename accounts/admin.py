from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "username",
        "email",
        "company_name",
        "is_staff",
        "is_active",
    )
    search_fields = ("username", "email", "company_name", "first_name", "last_name")
    filter_horizontal = BaseUserAdmin.filter_horizontal + ("warehouses",)
    fieldsets = BaseUserAdmin.fieldsets + (
        (
            "Buyer info",
            {"fields": ("company_name", "phone", "warehouses")},
        ),
    )
