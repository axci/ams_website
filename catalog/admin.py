from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path
from django.utils.html import format_html

from warehouses.models import Stock

from .forms import ProductImportForm
from .imports import import_products
from .models import (
    BannerSlide,
    Brand,
    Category,
    ModelProduct,
    Product,
    SubCategory,
)


class SubCategoryInline(admin.TabularInline):
    model = SubCategory
    extra = 1
    fields = ("name", "order")


class ProductStockInline(admin.TabularInline):
    model = Stock
    extra = 1
    autocomplete_fields = ("warehouse",)


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ("name", "order", "slug")
    list_editable = ("order",)
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name",)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "order", "subcategory_count")
    list_editable = ("order",)
    search_fields = ("name",)
    inlines = [SubCategoryInline]

    @admin.display(description="Subcategories")
    def subcategory_count(self, obj):
        return obj.subcategories.count()


@admin.register(SubCategory)
class SubCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "order")
    list_editable = ("order",)
    list_filter = ("category",)
    search_fields = ("name", "category__name")


@admin.register(ModelProduct)
class ModelProductAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    change_list_template = "admin/catalog/product/change_list.html"
    list_display = (
        "sku",
        "article",
        "name",
        "brand",
        "category",
        "subcategory",
        "model_product",
        "weight",
        "volume",
        "price",
        "is_active",
    )
    list_filter = ("brand", "category", "subcategory", "model_product", "is_active")
    search_fields = ("sku", "article", "manufacturer_number", "name", "description")
    autocomplete_fields = ("brand", "category", "subcategory", "model_product")
    inlines = [ProductStockInline]

    def get_urls(self):
        custom = [
            path(
                "import-excel/",
                self.admin_site.admin_view(self.import_excel),
                name="catalog_product_import_excel",
            ),
        ]
        return custom + super().get_urls()

    def import_excel(self, request):
        if request.method == "POST":
            form = ProductImportForm(request.POST, request.FILES)
            if form.is_valid():
                result = import_products(
                    form.cleaned_data["file"], form.cleaned_data["brand"]
                )
                self.message_user(
                    request,
                    f"Import finished: {result.created} created, "
                    f"{result.updated} updated, {result.skipped} skipped, "
                    f"{len(result.errors)} error row(s).",
                    level=messages.SUCCESS if not result.errors else messages.WARNING,
                )
                if result.warehouses:
                    self.message_user(
                        request,
                        "Stock updated for warehouse(s): "
                        + ", ".join(result.warehouses),
                        level=messages.INFO,
                    )
                for row_num, msg in result.errors[:15]:
                    self.message_user(request, f"Row {row_num}: {msg}", messages.ERROR)
                if len(result.errors) > 15:
                    self.message_user(
                        request,
                        f"…and {len(result.errors) - 15} more error row(s).",
                        messages.ERROR,
                    )
                return redirect("admin:catalog_product_changelist")
        else:
            form = ProductImportForm()

        context = {
            **self.admin_site.each_context(request),
            "title": "Import products from Excel",
            "form": form,
            "opts": self.model._meta,
        }
        return render(request, "admin/catalog/product/import_excel.html", context)


@admin.register(BannerSlide)
class BannerSlideAdmin(admin.ModelAdmin):
    list_display = ("thumbnail", "caption", "order", "is_active")
    list_display_links = ("thumbnail",)
    list_editable = ("order", "is_active")
    search_fields = ("caption",)

    @admin.display(description="Preview")
    def thumbnail(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="height:44px;border-radius:4px;">', obj.image.url
            )
        return "—"
