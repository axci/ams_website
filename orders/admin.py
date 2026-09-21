from io import BytesIO

from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path

from .models import (
    Cart,
    CartItem,
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


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "warehouse", "status", "payment_method", "delivery_method", "total", "created_at")
    list_filter = ("status", "payment_method", "delivery_method", "warehouse", "created_at")
    search_fields = ("id", "user__username", "user__company_name", "items__sku")
    readonly_fields = ("total", "created_at", "updated_at")
    inlines = [OrderItemInline]


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
