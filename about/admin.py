from django.contrib import admin
from django.db import models
from django.utils.html import format_html, strip_tags
from tinymce.widgets import TinyMCE

from .models import AboutBlock, CompanyDetails


@admin.register(AboutBlock)
class AboutBlockAdmin(admin.ModelAdmin):
    list_display = ("thumbnail", "title", "preview", "has_file", "order", "is_published")
    list_display_links = ("preview",)
    list_editable = ("order", "is_published")
    search_fields = ("title", "text")
    formfield_overrides = {models.TextField: {"widget": TinyMCE()}}

    @admin.display(description="Изображение")
    def thumbnail(self, obj):
        if obj.picture:
            return format_html(
                '<img src="{}" style="height:40px;width:60px;object-fit:cover;'
                'border-radius:4px;">',
                obj.picture.url,
            )
        return "—"

    @admin.display(description="Текст")
    def preview(self, obj):
        text = strip_tags(obj.text or "").strip()
        if not text:
            return "—"
        return (text[:80] + "…") if len(text) > 80 else text

    @admin.display(description="Файл", boolean=True)
    def has_file(self, obj):
        return bool(obj.file)


@admin.register(CompanyDetails)
class CompanyDetailsAdmin(admin.ModelAdmin):
    list_display = ("name", "inn", "kpp")

    def has_add_permission(self, request):
        # Singleton: only one record allowed.
        return not CompanyDetails.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
