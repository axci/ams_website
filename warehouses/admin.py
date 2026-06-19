from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import Manager, Stock, Warehouse


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "email", "stock_count", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "code")
    filter_horizontal = ("managers",)
    readonly_fields = ("stock_link",)

    @admin.display(description="Позиций")
    def stock_count(self, obj):
        return obj.stocks.count()

    @admin.display(description="Остатки")
    def stock_link(self, obj):
        # Editing stock inline here doesn't scale: a warehouse can hold
        # thousands of rows (Новосибирск has ~1500), which froze this page.
        # Manage stock on the paginated Stock changelist instead.
        if obj.pk is None:
            return "Сохраните склад, затем добавляйте остатки на странице «Запасы»."
        url = reverse("admin:warehouses_stock_changelist") + f"?warehouse__id__exact={obj.pk}"
        return format_html(
            '<a class="button" href="{}">Открыть остатки склада ({} поз.)</a>',
            url, obj.stocks.count(),
        )


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
