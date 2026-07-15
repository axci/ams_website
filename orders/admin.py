from django.contrib import admin

from .models import Cart, CartItem, Order, OrderItem


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
    list_display = ("id", "user", "warehouse", "status", "payment_method", "total", "created_at")
    list_filter = ("status", "payment_method", "warehouse", "created_at")
    search_fields = ("id", "user__username", "user__company_name", "items__sku")
    readonly_fields = ("total", "created_at", "updated_at")
    inlines = [OrderItemInline]
