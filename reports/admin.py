from django.contrib import admin
from django.db.models import Sum
from django.shortcuts import render
from django.urls import path
from django.utils.dateparse import parse_date

from .models import CashflowDocument

# «Поступление» — money in; everything else counts as money out.
INCOME_PREFIX = "Поступ"

# Fields that come from 1С (a mirror) — read-only; only «note» is editable.
ONEC_FIELDS = (
    "number", "date", "amount", "direction", "source", "doc_type",
    "organization", "counterparty", "article", "comment", "purpose", "synced_at",
)


def _totals(qs):
    """Поступление / Расход / Сальдо (+ count) for a queryset."""
    income = qs.filter(direction__istartswith=INCOME_PREFIX).aggregate(s=Sum("amount"))["s"] or 0
    outflow = qs.exclude(direction__istartswith=INCOME_PREFIX).aggregate(s=Sum("amount"))["s"] or 0
    return {"income": income, "outflow": outflow, "net": income - outflow, "count": qs.count()}


@admin.register(CashflowDocument)
class CashflowDocumentAdmin(admin.ModelAdmin):
    """1С cash-flow mirror. The changelist is the quick report (date drill-down,
    filters, totals); «Сформировать отчёт» opens a period report. Rows are managed
    by the sync, so the 1С fields are read-only and only «Заметка» is editable."""

    change_list_template = "admin/reports/cashflowdocument/change_list.html"
    date_hierarchy = "date"
    list_display = (
        "date", "number", "direction", "source", "amount",
        "organization", "counterparty", "article", "note",
    )
    list_filter = ("direction", "source", "organization", "article", "date")
    search_fields = ("number", "counterparty", "organization", "article",
                     "comment", "purpose", "note")
    ordering = ("-date", "-number")
    readonly_fields = ONEC_FIELDS

    # The sync owns the rows (full refresh); no manual add/delete. «note» stays
    # editable (preserved across syncs).
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        custom = [
            path(
                "report/",
                self.admin_site.admin_view(self.report_view),
                name="reports_cashflow_report",
            ),
        ]
        return custom + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context)
        try:
            qs = response.context_data["cl"].queryset
        except (AttributeError, KeyError):
            return response  # e.g. a redirect from an invalid filter
        response.context_data["cashflow_totals"] = _totals(qs)
        return response

    def report_view(self, request):
        """Period report: «с … по …» → totals + the documents for that range."""
        date_from = parse_date((request.GET.get("from") or "").strip())
        date_to = parse_date((request.GET.get("to") or "").strip())
        submitted = "form" in request.GET
        totals = rows = None
        row_cap = 1000
        if submitted:
            qs = CashflowDocument.objects.all()
            if date_from:
                qs = qs.filter(date__gte=date_from)
            if date_to:
                qs = qs.filter(date__lte=date_to)
            totals = _totals(qs)
            rows = list(qs[:row_cap])
        context = {
            **self.admin_site.each_context(request),
            "title": "Денежный поток — отчёт за период",
            "opts": self.model._meta,
            "date_from": request.GET.get("from", ""),
            "date_to": request.GET.get("to", ""),
            "submitted": submitted,
            "totals": totals,
            "rows": rows,
            "row_cap": row_cap,
        }
        return render(request, "admin/reports/cashflowdocument/report.html", context)
