from django.contrib import admin
from django.utils.html import format_html

from .models import (
    AboutBrandBlock,
    AboutBrandChip,
    AboutPage,
    AboutSpec,
    ClientTag,
    CompanyDetails,
    SupplyCenter,
    SupplyRegion,
)

# AboutBlock is superseded by the structured AboutPage below; its model and data
# are kept, but it is intentionally not registered in the admin.


class AboutSpecInline(admin.TabularInline):
    model = AboutSpec
    extra = 0
    verbose_name = "показатель шапки"
    verbose_name_plural = "Показатели шапки — Год основания, Регион, Направление"


class ClientTagInline(admin.TabularInline):
    model = ClientTag
    extra = 0


class SupplyCenterInline(admin.TabularInline):
    model = SupplyCenter
    extra = 0


class SupplyRegionInline(admin.TabularInline):
    model = SupplyRegion
    extra = 0


@admin.register(AboutPage)
class AboutPageAdmin(admin.ModelAdmin):
    inlines = [AboutSpecInline, ClientTagInline, SupplyCenterInline, SupplyRegionInline]
    fieldsets = (
        ("Hero", {
            "fields": ("hero_eyebrow", "hero_title", "hero_title_accent", "hero_lead"),
            "description": "Плитки «Год основания», «Регион», «Направление» "
                           "редактируются ниже на этой странице — в разделе "
                           "«Показатели шапки».",
        }),
        ("Профиль", {"fields": ("profile_eyebrow", "profile_title", "profile_side_label",
                                "profile_lead", "profile_body", "profile_pull")}),
        ("Клиенты", {"fields": ("clients_eyebrow", "clients_title", "clients_body")}),
        ("Бренды", {"fields": ("brands_eyebrow", "brands_title"),
                    "description": "Сами блоки брендов редактируются в разделе «Блоки брендов»."}),
        ("География", {"fields": ("geo_eyebrow", "geo_title")}),
        ("Реквизиты", {"fields": ("req_eyebrow", "req_title", "req_note"),
                       "description": "Числа реквизитов и PDF — в разделе «Реквизиты компании»."}),
    )

    def has_add_permission(self, request):
        return not AboutPage.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


class AboutBrandChipInline(admin.TabularInline):
    model = AboutBrandChip
    extra = 1
    fields = ("name", "image", "preview", "url", "order")
    readonly_fields = ("preview",)

    @admin.display(description="Логотип")
    def preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="height:32px;max-width:90px;object-fit:contain">',
                obj.image.url,
            )
        return "—"


@admin.register(AboutBrandBlock)
class AboutBrandBlockAdmin(admin.ModelAdmin):
    list_display = ("heading", "role", "chip_count", "order", "is_published")
    list_editable = ("order", "is_published")
    inlines = [AboutBrandChipInline]

    @admin.display(description="Плиток")
    def chip_count(self, obj):
        return obj.chips.count()


@admin.register(CompanyDetails)
class CompanyDetailsAdmin(admin.ModelAdmin):
    list_display = ("short_name", "inn", "kpp")

    def has_add_permission(self, request):
        return not CompanyDetails.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
