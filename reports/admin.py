from django.contrib import admin
from django.db.models import Sum

from .models import CashflowDocument

# «Поступление» — money in; everything else counts as money out.
INCOME_PREFIX = "Поступ"


@admin.register(CashflowDocument)
class CashflowDocumentAdmin(admin.ModelAdmin):
    """Read-only admin report. Data is populated by the ``sync_cashflow`` command;
    the changelist is the report — date drill-down, filters, and period totals."""

    change_list_template = "admin/reports/cashflowdocument/change_list.html"
    date_hierarchy = "date"
    list_display = (
        "date", "number", "direction", "source", "amount",
        "organization", "counterparty", "article",
    )
    list_filter = ("direction", "source", "organization", "article", "date")
    search_fields = ("number", "counterparty", "organization", "article", "comment", "purpose")
    ordering = ("-date", "-number")

    # Pure report — the sync owns the data.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context)
        try:
            qs = response.context_data["cl"].queryset
        except (AttributeError, KeyError):
            return response  # e.g. a redirect from an invalid filter
        income = qs.filter(direction__istartswith=INCOME_PREFIX).aggregate(s=Sum("amount"))["s"] or 0
        outflow = qs.exclude(direction__istartswith=INCOME_PREFIX).aggregate(s=Sum("amount"))["s"] or 0
        response.context_data["cashflow_totals"] = {
            "income": income,
            "outflow": outflow,
            "net": income - outflow,
            "count": qs.count(),
        }
        return response
