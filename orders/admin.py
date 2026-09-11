from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path

from .models import Cart, CartItem, Order, OrderItem, SalesRecord
from .sales_import import import_sales


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
                result = import_sales(form.cleaned_data["file"])
                self.message_user(
                    request,
                    f"Импорт завершён: добавлено {result.created}, "
                    f"обновлено {result.updated}, пропущено {result.skipped}, "
                    f"без товара в каталоге {result.unmatched_sku}, "
                    f"ошибок {len(result.errors)}.",
                    level=messages.SUCCESS if not result.errors else messages.WARNING,
                )
                for row_num, msg in result.errors[:15]:
                    self.message_user(request, f"Строка {row_num}: {msg}", messages.ERROR)
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
