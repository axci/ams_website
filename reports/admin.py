from django.contrib import admin
from django.db.models import Count, Sum
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import path
from django.utils import timezone

from .cashflow_report import (
    build_cashflow_documents_xlsx,
    build_cashflow_odds_xlsx,
    build_rows,
)
from .models import CashflowArticleMapping, CashflowDocument, Receipt, ReceiptLine

# «Поступление» — money in; everything else counts as money out.
INCOME_PREFIX = "Поступ"

_MONTHS_RU = ["", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль",
              "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]


def _totals(qs):
    """Поступление / Расход / Сальдо (+ count) for a queryset."""
    income = qs.filter(direction__istartswith=INCOME_PREFIX).aggregate(s=Sum("amount"))["s"] or 0
    outflow = qs.exclude(direction__istartswith=INCOME_PREFIX).aggregate(s=Sum("amount"))["s"] or 0
    return {"income": income, "outflow": outflow, "net": income - outflow, "count": qs.count()}


@admin.register(CashflowDocument)
class CashflowDocumentAdmin(admin.ModelAdmin):
    """1С cash-flow mirror. The changelist is the quick report (date drill-down,
    filters, totals); «Сформировать отчёт» opens the ОДДС. All fields are editable;
    «Заметка» survives a sync, the 1С fields are refreshed from 1С on the next sync."""

    change_list_template = "admin/reports/cashflowdocument/change_list.html"
    date_hierarchy = "date"
    list_display = (
        "date", "number", "direction", "source", "amount",
        "organization", "counterparty", "article", "manual",
    )
    list_filter = ("manual", "direction", "source", "organization", "article", "date")
    search_fields = ("number", "counterparty", "organization", "article",
                     "comment", "purpose", "note")
    ordering = ("-date", "-number")

    def get_readonly_fields(self, request, obj=None):
        # «synced_at» is always auto-managed; «manual» is shown read-only on an
        # existing document (it is set automatically, never edited by hand).
        return ("synced_at", "manual") if obj is not None else ("synced_at",)

    # The sync owns the 1С rows (full refresh). Documents may be added by hand;
    # such rows are flagged manual=True so the sync keeps them, and only those
    # hand-added rows may be deleted here — synced rows stay protected.
    def has_add_permission(self, request):
        return True

    def has_delete_permission(self, request, obj=None):
        return bool(obj is not None and obj.manual)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.manual = True  # mark hand-added docs so the sync won't wipe them
        super().save_model(request, obj, form, change)

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
        thousands = request.GET.get("units") == "thousands"

        fmt = request.GET.get("format")
        if fmt in ("xlsx", "docs"):
            if fmt == "docs":
                data = build_cashflow_documents_xlsx(month, year)
                fname = f"cashflow_documents_{year}-{month:02d}.xlsx"
            else:
                data = build_cashflow_odds_xlsx(month, year, thousands=thousands)
                fname = f"cashflow_{year}-{month:02d}{'_thousands' if thousands else ''}.xlsx"
            response = HttpResponse(
                data,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response["Content-Disposition"] = f'attachment; filename="{fname}"'
            return response

        context = {
            **self.admin_site.each_context(request),
            "title": "Отчёт о движении денежных средств",
            "opts": self.model._meta,
            "month": month,
            "year": year,
            "thousands": thousands,
            "months": list(enumerate(_MONTHS_RU[1:], start=1)),
            "years": list(range(today.year, today.year - 8, -1)),
        }
        context["rows"], context["diag"] = build_rows(month, year, thousands=thousands)
        return render(request, "admin/reports/cashflowdocument/report.html", context)


@admin.register(CashflowArticleMapping)
class CashflowArticleMappingAdmin(admin.ModelAdmin):
    list_display = ("article", "report_line", "exclude")
    list_editable = ("report_line", "exclude")
    search_fields = ("article", "report_line")
    ordering = ("article",)


class ReceiptLineInline(admin.TabularInline):
    model = ReceiptLine
    extra = 0
    can_delete = False
    fields = ("is_expense", "product", "quantity", "price", "line_sum")
    readonly_fields = fields
    ordering = ("is_expense", "id")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    """Goods receipts synced from 1С — the cost side of the profit report.
    Read-only: the `sync_receipts` command owns the rows (full refresh)."""

    date_hierarchy = "date"
    list_display = ("date", "number", "operation_type", "organization",
                    "counterparty", "warehouse", "amount", "lines_count")
    list_filter = ("operation_type", "organization", "warehouse", "date")
    search_fields = ("number", "counterparty", "organization", "warehouse")
    ordering = ("-date", "-number")
    inlines = [ReceiptLineInline]
    readonly_fields = ("number", "date", "operation_type", "organization",
                       "counterparty", "warehouse", "amount", "synced_at")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_lines=Count("lines"))

    @admin.display(description="строк", ordering="_lines")
    def lines_count(self, obj):
        return obj._lines

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
