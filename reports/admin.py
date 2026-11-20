from django.contrib import admin
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import path
from django.utils import timezone

from .cashflow_report import build_cashflow_odds_xlsx, build_rows
from .models import CashflowDocument

# «Поступление» — money in; everything else counts as money out.
INCOME_PREFIX = "Поступ"

_MONTHS_RU = ["", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль",
              "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]

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
        """ОДДС — cash-flow statement for a chosen Месяц + Год, on-screen or .xlsx."""
        today = timezone.localdate()
        try:
            month = int(request.GET.get("month") or today.month)
            year = int(request.GET.get("year") or today.year)
        except (TypeError, ValueError):
            month, year = today.month, today.year
        month = min(max(month, 1), 12)

        if request.GET.get("format") == "xlsx":
            data = build_cashflow_odds_xlsx(month, year)
            response = HttpResponse(
                data,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response["Content-Disposition"] = f'attachment; filename="cashflow_{year}-{month:02d}.xlsx"'
            return response

        context = {
            **self.admin_site.each_context(request),
            "title": "Отчёт о движении денежных средств",
            "opts": self.model._meta,
            "month": month,
            "year": year,
            "months": list(enumerate(_MONTHS_RU[1:], start=1)),
            "years": list(range(today.year, today.year - 8, -1)),
            "rows": build_rows(month, year),
        }
        return render(request, "admin/reports/cashflowdocument/report.html", context)
