from django.contrib import admin
from django.db import models
from django.utils.html import format_html
from tinymce.widgets import TinyMCE

from .models import News


@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    list_display = ("thumbnail", "title", "date", "is_published")
    list_display_links = ("title",)
    list_editable = ("is_published",)
    list_filter = ("is_published", "date")
    search_fields = ("title", "text")
    date_hierarchy = "date"
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
