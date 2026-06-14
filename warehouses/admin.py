from django.contrib import admin
from django.utils.html import format_html

from .models import Manager, Stock, Warehouse


class StockInline(admin.TabularInline):
    model = Stock
    extra = 1
    autocomplete_fields = ("product",)


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "email", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "code")
    filter_horizontal = ("managers",)
    inlines = [StockInline]


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ("product", "warehouse", "quantity", "updated_at")
    list_filter = ("warehouse",)
    search_fields = ("product__sku", "product__article", "product__name")
    autocomplete_fields = ("product", "warehouse")
    list_editable = ("quantity",)


@admin.register(Manager)
class ManagerAdmin(admin.ModelAdmin):
    list_display = ("thumbnail", "order", "surname", "name", "position", "phone", "email")
    list_display_links = ("surname", "name")
    list_editable = ("order",)
    search_fields = ("surname", "name", "position", "phone", "email")

    @admin.display(description="Фото")
    def thumbnail(self, obj):
        if obj.photo:
            return format_html(
                '<img src="{}" style="height:36px;width:36px;object-fit:cover;border-radius:50%;">',
                obj.photo.url,
            )
        return "—"
