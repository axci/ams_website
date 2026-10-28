from io import BytesIO

from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path

from .models import (
    Cart,
    CartItem,
    ImportedOrderEmail,
    Order,
    OrderItem,
    PurchaseOrder,
    PurchaseOrderItem,
    SalesRecord,
    StockSnapshot,
)
from .sales_import import import_sales
from .stock_import import import_stock


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    autocomplete_fields = ("product",)


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ("user", "items_count", "total", "updated_at")
    search_fields = ("user__username",)
    inlines = [CartItemInline]


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    autocomplete_fields = ("product",)
    readonly_fields = ("subtotal",)

    @admin.display(description="Subtotal")
    def subtotal(self, obj):
        return obj.subtotal


class Exported1CFilter(admin.SimpleListFilter):
    title = "выгрузка в 1С"
    parameter_name = "exported_1c"

    def lookups(self, request, model_admin):
        return [("yes", "Выгружен"), ("no", "Не выгружен")]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(exported_to_1c_at__isnull=False)
        if self.value() == "no":
            return queryset.filter(exported_to_1c_at__isnull=True)
        return queryset


class ImportedFilter(admin.SimpleListFilter):
    title = "импорт из почты"
    parameter_name = "imported"

    def lookups(self, request, model_admin):
        return [("yes", "Из письма"), ("no", "Обычные")]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(imported_from_email__isnull=False)
        if self.value() == "no":
            return queryset.filter(imported_from_email__isnull=True)
        return queryset


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "warehouse", "status", "payment_method", "delivery_method", "total", "exported_1c", "from_email", "created_at")
    list_filter = ("status", "payment_method", "delivery_method", "warehouse", Exported1CFilter, ImportedFilter, "created_at")
    search_fields = ("id", "user__username", "user__company_name", "items__sku")
    readonly_fields = ("total", "created_at", "updated_at", "imported_from_email")
    inlines = [OrderItemInline]
    actions = ["mark_not_exported_1c", "mark_exported_1c"]

    @admin.display(description="В 1С", boolean=True, ordering="exported_to_1c_at")
    def exported_1c(self, obj):
        return obj.is_exported_to_1c

    @admin.display(description="Из почты", boolean=True, ordering="imported_from_email")
    def from_email(self, obj):
        return obj.imported_from_email_id is not None

    @admin.action(description="Пометить как НЕ выгруженные в 1С (отправить заново)")
    def mark_not_exported_1c(self, request, queryset):
        updated = queryset.update(exported_to_1c_at=None)
        self.message_user(
            request,
            f"Помечено как невыгруженные: {updated}. "
            "Будут выгружены при следующем обмене с 1С.",
        )

    @admin.action(description="Пометить как выгруженные в 1С")
    def mark_exported_1c(self, request, queryset):
        from django.utils import timezone

        updated = queryset.filter(exported_to_1c_at__isnull=True).update(
            exported_to_1c_at=timezone.now()
        )
        self.message_user(request, f"Помечено как выгруженные: {updated}.")


class SalesImportForm(forms.Form):
    file = forms.FileField(label="Excel-файл (.xlsx) из 1С")


@admin.register(SalesRecord)
class SalesRecordAdmin(admin.ModelAdmin):
    change_list_template = "admin/orders/salesrecord/change_list.html"
    list_display = ("date", "warehouse", "product", "sku", "client", "quantity", "document_type")
    list_filter = ("warehouse", "document_type", "date")
    search_fields = ("sku", "client", "document", "product__name")
    list_select_related = ("warehouse", "product")
    date_hierarchy = "date"
    autocomplete_fields = ("product", "warehouse")

    def get_urls(self):
        custom = [
            path(
                "import-excel/",
                self.admin_site.admin_view(self.import_excel),
                name="orders_salesrecord_import_excel",
            ),
        ]
        return custom + super().get_urls()

    def import_excel(self, request):
        if request.method == "POST":
            form = SalesImportForm(request.POST, request.FILES)
            if form.is_valid():
                # One upload builds both sales records and stock history.
                data = form.cleaned_data["file"].read()
                sales = import_sales(BytesIO(data))
                stock = import_stock(BytesIO(data))
                summary = (
                    f"Продажи: добавлено {sales.created}, обновлено {sales.updated}, "
                    f"пропущено {sales.skipped}, без товара {sales.unmatched_sku}."
                )
                if stock.period_start:
                    summary += (
                        f" Остатки: {stock.snapshots} записей за "
                        f"{stock.period_start:%d.%m.%Y}–{stock.period_end:%d.%m.%Y}."
                    )
                self.message_user(
                    request,
                    summary,
                    level=messages.SUCCESS if not sales.errors else messages.WARNING,
                )
                for row_num, msg in sales.errors[:10]:
                    self.message_user(request, f"Продажи, строка {row_num}: {msg}", messages.ERROR)
                for row_num, msg in stock.errors[:10]:
                    self.message_user(request, f"Остатки, строка {row_num}: {msg}", messages.ERROR)
                return redirect("admin:orders_salesrecord_changelist")
        else:
            form = SalesImportForm()
        context = {
            **self.admin_site.each_context(request),
            "title": "Импорт статистики продаж из 1С",
            "form": form,
            "opts": self.model._meta,
        }
        return render(request, "admin/orders/salesrecord/import_excel.html", context)


class StockImportForm(forms.Form):
    file = forms.FileField(label="Excel-файл (.xlsx) из 1С")


@admin.register(StockSnapshot)
class StockSnapshotAdmin(admin.ModelAdmin):
    change_list_template = "admin/orders/stocksnapshot/change_list.html"
    list_display = ("date", "warehouse", "product", "sku", "quantity")
    list_filter = ("warehouse", "date")
    search_fields = ("sku", "product__name")
    list_select_related = ("warehouse", "product")
    date_hierarchy = "date"

    def get_urls(self):
        custom = [
            path(
                "import-excel/",
                self.admin_site.admin_view(self.import_excel),
                name="orders_stocksnapshot_import_excel",
            ),
        ]
        return custom + super().get_urls()

    def import_excel(self, request):
        if request.method == "POST":
            form = StockImportForm(request.POST, request.FILES)
            if form.is_valid():
                result = import_stock(form.cleaned_data["file"])
                if result.errors:
                    for row_num, msg in result.errors[:15]:
                        self.message_user(request, f"Строка {row_num}: {msg}", messages.ERROR)
                else:
                    self.message_user(
                        request,
                        f"Импорт остатков завершён: {result.snapshots} записей "
                        f"по {result.pairs} парам (товар × склад) за период "
                        f"{result.period_start:%d.%m.%Y}–{result.period_end:%d.%m.%Y}; "
                        f"без товара в каталоге {result.unmatched_sku}.",
                        level=messages.SUCCESS,
                    )
                return redirect("admin:orders_stocksnapshot_changelist")
        else:
            form = StockImportForm()
        context = {
            **self.admin_site.each_context(request),
            "title": "Импорт истории остатков из 1С",
            "form": form,
            "opts": self.model._meta,
        }
        return render(request, "admin/orders/stocksnapshot/import_excel.html", context)


class PurchaseOrderItemInline(admin.TabularInline):
    model = PurchaseOrderItem
    extra = 0
    fields = ("sku", "name", "current_stock", "avg_daily_sales", "suggested_qty", "quantity")
    readonly_fields = ("sku", "name", "current_stock", "avg_daily_sales", "suggested_qty")


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ("id", "supplier", "created_at", "positions", "total_qty", "created_by")
    list_filter = ("supplier", "created_at")
    search_fields = ("supplier", "items__sku", "items__name")
    date_hierarchy = "created_at"
    inlines = (PurchaseOrderItemInline,)
    readonly_fields = ("created_at",)


@admin.register(ImportedOrderEmail)
class ImportedOrderEmailAdmin(admin.ModelAdmin):
    list_display = ("processed_at", "sender", "subject", "order_count", "received_at")
    search_fields = ("sender", "subject", "message_id")
    date_hierarchy = "processed_at"
    readonly_fields = (
        "message_id", "sender", "subject", "received_at", "processed_at",
        "order_count", "report",
    )

    def has_add_permission(self, request):
        return False  # created only by the import command
