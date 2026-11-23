"""ОДДС — Отчёт о движении денежных средств (cash-flow statement).

Builds a fixed-taxonomy cash-flow statement for a given month+year from the
synced :class:`reports.models.CashflowDocument` rows: documents are summed per
«статья» (netto = поступления − расходы), mapped onto the fixed report lines,
rolled up into groups/sections and «Сальдо» rows, and compared month vs. same
month a year ago and year-to-date. Layout mirrors the client's Excel template.
"""
import calendar
import datetime
from decimal import Decimal
from io import BytesIO

import openpyxl
from django.db.models import Q, Sum
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

_MONTHS_RU = ["", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль",
              "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]

# 1С «статья» (lower-cased) -> report line. Articles not here fall into the
# catch-all «прочие расходы денежных средств»; EXCLUDED ones are dropped.
EXCLUDED = {"перемещение между кассами, счетами"}
CATCH_ALL_LINE = "прочие расходы денежных средств"

ARTICLE_TO_LINE = {
    # — Поступления —
    "оплата от покупателей": "Оплата от покупателей",
    "вознаграждение за логистику": "Вознаграждение за логистику",
    "поступления от аренды": "Поступления от аренды",
    "проценты по депозиту": "Проценты по депозиту",
    "проценты по дбс": "Проценты по депозиту",
    "прочие доходы": "Прочие поступления",
    "прочее": "Прочие поступления",
    # — Расходы по текущей деятельности —
    "оплата поставщикам": "Оплата поставщикам",
    "транспортные расходы": "транспортные расходы",
    "обслуживание автотранспорта": "обслуживание автотранспорта",
    "гсм": "ГСМ",
    "заработная плата": "заработная плата",
    "зарплата": "заработная плата",
    "отчисления от фот": "отчисления от ФОТ",
    "ндфл": "НДФЛ",
    "аренда помещений": "аренда помещений",
    "охрана": "охрана",
    "продвижение товара": "продвижение товара",
    "реклама и маркетинг": "реклама и маркетинг",
    "прочие коммерческие расходы": "прочие коммерческие расходы",
    "ндс": "НДС",
    "налог на прибыль": "налог на прибыль",
    "налог на имущество": "налог на имущество",
    "земельный налог": "земельный налог",
    "транспортный налог": "транспортный налог",
    "проценты по кредитам / займам": "Проценты по кредитам / займам",
    "личные средства предпринимателя": "Дивиденды",
    "представительские расходы": "представительские расходы",
    "расходы на вычислительную и орг.технику": "расходы на вычислительную и орг.технику",
    "програмное обеспечение": "програмное обеспечение",
    "банковское обслуживание": "банковское обслуживание",
    "хозяйственные расходы": "хозяйственные расходы",
    "обслуживание офиса": "обслуживание офиса",
    "упаковка": "упаковка",
    "юридические услуги": "юридические услуги",
    "услуги связи": "услуги связи",
    "штрафы, пени, неустойки": "штрафы, пени, неустойки",
    "электроэнергия": "электроэнергия",
    "газопотребление": "газопотребление",
    "мебель": "мебель",
    "прочие расходы денежных средств": "прочие расходы денежных средств",
    "командировки": "прочие расходы денежных средств",
    "коммунальные платежи": "прочие расходы денежных средств",
    # — Инвестиционная —
    "земельные участки": "Земельные участки",
    "земельные работы": "Земельные работы",
    "электромонтажные работы": "Электромонтажные работы",
    "приобретение ос": "Приобретение ОС",
    "покупка оборудования, помещений": "Приобретение ОС",
    "покупка техники": "Приобретение ОС",
    "проектные работы": "Проектные работы",
    "прочие инвестиционные платежи": "Прочие инвестиционные платежи",
    # — Финансовая —
    "получение кредитов и займов": "Кредиты банка",
    "возврат кредита /займа": "Кредиты банка",
    "займы": "Займы",
    "депозит": "Депозит",
}

# The fixed statement layout. Node = (label, kind[, children]); kind is one of
# sec / grp / sub / leaf / saldo / total. «saldo» sums its section's leaves;
# «total» sums every section.
STRUCTURE = [
    ("Текущая деятельность", "sec", [
        ("Поступления от текущей деятельности", "grp", [
            ("Оплата от покупателей", "leaf"),
            ("Вознаграждение за логистику", "leaf"),
            ("Поступления от аренды", "leaf"),
            ("Проценты по депозиту", "leaf"),
            ("Прочие поступления", "leaf"),
        ]),
        ("Расходы по текущей деятельности", "grp", [
            ("Оплата поставщикам", "leaf"),
            ("Затраты на транспорт", "sub", [
                ("транспортные расходы", "leaf"),
                ("обслуживание автотранспорта", "leaf"),
                ("ГСМ", "leaf"),
            ]),
            ("Расходы на заработную плату", "sub", [
                ("заработная плата", "leaf"),
                ("отчисления от ФОТ", "leaf"),
                ("НДФЛ", "leaf"),
            ]),
            ("Аренда помещения и охрана", "sub", [
                ("аренда помещений", "leaf"),
                ("охрана", "leaf"),
            ]),
            ("Коммерческие расходы", "sub", [
                ("продвижение товара", "leaf"),
                ("реклама и маркетинг", "leaf"),
                ("прочие коммерческие расходы", "leaf"),
            ]),
            ("Налоги", "sub", [
                ("НДС", "leaf"),
                ("налог на прибыль", "leaf"),
                ("налог на имущество", "leaf"),
                ("земельный налог", "leaf"),
                ("транспортный налог", "leaf"),
            ]),
            ("Проценты по кредитам / займам", "leaf"),
            ("Дивиденды", "leaf"),
            ("Прочие расходы", "sub", [
                ("представительские расходы", "leaf"),
                ("расходы на вычислительную и орг.технику", "leaf"),
                ("програмное обеспечение", "leaf"),
                ("канцелярия", "leaf"),
                ("карщик", "leaf"),
                ("банковское обслуживание", "leaf"),
                ("хозяйственные расходы", "leaf"),
                ("обслуживание офиса", "leaf"),
                ("упаковка", "leaf"),
                ("юридические услуги", "leaf"),
                ("услуги связи", "leaf"),
                ("штрафы, пени, неустойки", "leaf"),
                ("электроэнергия", "leaf"),
                ("газопотребление", "leaf"),
                ("мебель", "leaf"),
                ("прочие расходы денежных средств", "leaf"),
            ]),
        ]),
        ("Сальдо от текущей деятельности", "saldo"),
    ]),
    ("Инвестиционная деятельность", "sec", [
        ("Строительство, ремонт помещений", "leaf"),
        ("Земельные участки", "leaf"),
        ("Земельные работы", "leaf"),
        ("Электромонтажные работы", "leaf"),
        ("Приобретение ОС", "leaf"),
        ("Проектные работы", "leaf"),
        ("Прочие инвестиционные платежи", "leaf"),
        ("Сальдо от инвестиционной деятельности", "saldo"),
    ]),
    ("Финансовая деятельность", "sec", [
        ("Кредиты банка", "leaf"),
        ("Займы", "leaf"),
        ("Депозит", "leaf"),
        ("Сальдо от финансовой деятельности", "saldo"),
    ]),
    ("Сальдо денежных средств", "total"),
]

def _collect_leaves(nodes):
    for node in nodes:
        if node[1] == "leaf":
            yield node[0]
        elif len(node) > 2:
            yield from _collect_leaves(node[2])


# All report line labels (leaves) — the valid targets for an article mapping.
REPORT_LINES = []
for _node in STRUCTURE:
    if _node[1] == "sec":
        REPORT_LINES.extend(_collect_leaves(_node[2]))


def effective_mapping():
    """Article (lower-cased) -> (report_line | None, exclude). Hard-coded defaults
    merged with the admin-editable overrides (``CashflowArticleMapping``)."""
    mapping = {k: (v, False) for k, v in ARTICLE_TO_LINE.items()}
    for key in EXCLUDED:
        mapping[key] = (None, True)
    from .models import CashflowArticleMapping
    for row in CashflowArticleMapping.objects.all():
        key = (row.article or "").strip().lower()
        if not key:
            continue
        if row.exclude:
            mapping[key] = (None, True)
        elif row.report_line:
            mapping[key] = (row.report_line, False)
        # blank line and not excluded -> leave the default in place
    return mapping


_PERIODS = ("cur", "prev", "ytd", "pytd")


def _last_day(year, month):
    return datetime.date(year, month, calendar.monthrange(year, month)[1])


def _growth(cur, prev):
    """Dynamics (cur−prev)/prev as a float ratio; None when prev is 0."""
    return float((cur - prev) / prev) if prev else None


def _line_net(date_from, date_to, mapping, unmapped):
    """Netto (поступления − расходы) per report line for the date range.

    ``mapping`` comes from :func:`effective_mapping`. Articles absent from it are
    put in the catch-all line and recorded in the ``unmapped`` set for the warning.
    """
    from .models import CashflowDocument

    agg = (
        CashflowDocument.objects
        .filter(date__gte=date_from, date__lte=date_to)
        .values("article")
        .annotate(
            inc=Sum("amount", filter=Q(direction__istartswith="Поступ")),
            out=Sum("amount", filter=~Q(direction__istartswith="Поступ")),
        )
    )
    lines = {}
    for row in agg:
        raw = (row["article"] or "").strip()
        target = mapping.get(raw.lower())
        if target is not None and target[1]:
            continue  # excluded from the report
        if target is None:
            unmapped.add(raw)
            line = CATCH_ALL_LINE
        else:
            line = target[0] or CATCH_ALL_LINE
        net = (row["inc"] or Decimal(0)) - (row["out"] or Decimal(0))
        lines[line] = lines.get(line, Decimal(0)) + net
    return lines


def _period_totals(date_from, date_to):
    """(total_net, transfers_net) for a range: netto of ALL documents, and of the
    «Перемещение между кассами, счетами» article (own-account transfers)."""
    from .models import CashflowDocument

    def _net(qs):
        agg = qs.aggregate(
            inc=Sum("amount", filter=Q(direction__istartswith="Поступ")),
            out=Sum("amount", filter=~Q(direction__istartswith="Поступ")),
        )
        return (agg["inc"] or Decimal(0)) - (agg["out"] or Decimal(0))

    base = CashflowDocument.objects.filter(date__gte=date_from, date__lte=date_to)
    total = _net(base)
    transfers = _net(base.filter(article__iexact="Перемещение между кассами, счетами"))
    return total, transfers


def build_rows(month, year, thousands=False):
    """Return ``(rows, diag)``: the statement as a flat ordered list of
    {label, depth, kind, cols} (cols None for section headers), plus a diagnostics
    dict (unmapped articles, transfers netto, and the balance reconciliation for
    the selected month). ``thousands`` divides every money value by 1000 (тыс. руб.)
    for the display strings and the numeric ``cols``; ratios (%) and the raw diag
    values stay unscaled so the reconciliation keeps its ₽ tolerance."""
    mapping = effective_mapping()
    unmapped = set()
    scale = Decimal(1000) if thousands else Decimal(1)

    def net(df, dt):
        return _line_net(df, dt, mapping, unmapped)

    nets = {
        "cur": net(datetime.date(year, month, 1), _last_day(year, month)),
        "prev": net(datetime.date(year - 1, month, 1), _last_day(year - 1, month)),
        "ytd": net(datetime.date(year, 1, 1), _last_day(year, month)),
        "pytd": net(datetime.date(year - 1, 1, 1), _last_day(year - 1, month)),
    }

    def zero():
        return {p: Decimal(0) for p in _PERIODS}

    def add(a, b):
        return {p: a[p] + b[p] for p in _PERIODS}

    rows = []

    def emit(node, depth):
        label, kind = node[0], node[1]
        if kind == "leaf":
            base = {p: nets[p].get(label, Decimal(0)) for p in _PERIODS}
            rows.append({"label": label, "depth": depth, "kind": kind, "base": base})
            return base
        rows.append({"label": label, "depth": depth, "kind": kind, "base": None})
        idx = len(rows) - 1
        base = zero()
        for child in node[2]:
            base = add(base, emit(child, depth + 1))
        rows[idx]["base"] = base
        return base

    section_totals = []
    for node in STRUCTURE:
        label, kind = node[0], node[1]
        if kind == "total":
            total = zero()
            for s in section_totals:
                total = add(total, s)
            rows.append({"label": label, "depth": 0, "kind": "total", "base": total})
            continue
        # section
        rows.append({"label": label, "depth": 0, "kind": "sec", "base": None})
        sec_base = zero()
        saldo_idx = None
        for child in node[2]:
            if child[1] == "saldo":
                rows.append({"label": child[0], "depth": 1, "kind": "saldo", "base": None})
                saldo_idx = len(rows) - 1
                continue
            sec_base = add(sec_base, emit(child, 1))
        if saldo_idx is not None:
            rows[saldo_idx]["base"] = sec_base
        section_totals.append(sec_base)

    def _money(v):
        if v == 0:
            return ""
        s = f"{v / scale:,.0f}".replace(",", " ")
        return "0" if s == "-0" else s

    def _pct(ratio):
        return "" if ratio is None else f"{ratio * 100:,.0f}%".replace(",", " ")

    out = []
    for r in rows:
        base = r["base"]
        cols = None
        if base is not None:
            c, d, g, h = base["cur"], base["prev"], base["ytd"], base["pytd"]
            pm, py = _growth(c, d), _growth(g, h)
            cols = {
                "cur": c / scale, "prev": d / scale, "diff_m": (c - d) / scale, "pct_m": pm,
                "ytd": g / scale, "pytd": h / scale, "diff_y": (g - h) / scale, "pct_y": py,
                # display strings (HTML); the .xlsx uses the raw values above.
                "cur_disp": _money(c), "prev_disp": _money(d),
                "diff_m_disp": _money(c - d), "pct_m_disp": _pct(pm),
                "ytd_disp": _money(g), "pytd_disp": _money(h),
                "diff_y_disp": _money(g - h), "pct_y_disp": _pct(py),
            }
        out.append({"label": r["label"], "depth": r["depth"], "kind": r["kind"], "cols": cols})

    # Control checks for the selected month — kept in full rubles (the ₽ tolerance
    # is meaningful there); only the display strings follow the chosen scale.
    total_net, transfers_net = _period_totals(datetime.date(year, month, 1), _last_day(year, month))
    report_saldo = next(
        (r["base"]["cur"] for r in rows if r["kind"] == "total" and r["base"]),
        Decimal(0),
    )
    discrepancy = total_net - report_saldo
    tol = Decimal("0.5")

    def _fmt_s(v):
        s = f"{v / scale:,.0f}".replace(",", " ")
        return "0" if s == "-0" else s

    diag = {
        "unmapped": sorted(unmapped),
        "transfers_net": transfers_net,
        "transfers_net_disp": _fmt_s(transfers_net),
        "transfers_ok": abs(transfers_net) < tol,
        "report_saldo": report_saldo,
        "report_saldo_disp": _fmt_s(report_saldo),
        "total_net": total_net,
        "total_net_disp": _fmt_s(total_net),
        "discrepancy": discrepancy,
        "discrepancy_disp": _fmt_s(discrepancy),
        "balanced": abs(discrepancy) < tol,
    }
    return out, diag


_COL_KEYS = ("cur", "prev", "diff_m", "pct_m", "ytd", "pytd", "diff_y", "pct_y")
_HEADERS = ["месяц текущий", "месяц год назад", " +/-", "%",
            "с начала года", "с начала предыдущего года", " +/-", "%"]
_BOLD_KINDS = {"sec", "grp", "sub", "saldo", "total"}


_NUM_FMT = "#,##0;[Red]-#,##0"   # negatives in red
_PCT_FMT = "0%;[Red]-0%"
_LAST_COL = 10  # J
_HEADER_FILL = PatternFill("solid", fgColor="4472C4")
_ROW_FILLS = {
    "sec": PatternFill("solid", fgColor="D9E1F2"),
    "grp": PatternFill("solid", fgColor="F2F2F2"),
    "saldo": PatternFill("solid", fgColor="FFF2CC"),
    "total": PatternFill("solid", fgColor="D9E1F2"),
}


def build_cashflow_odds_xlsx(month, year, thousands=False):
    """Return the ОДДС for month+year as formatted .xlsx bytes (``thousands`` → тыс. руб.)."""
    rows, _diag = build_rows(month, year, thousands=thousands)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "cf"
    ws.sheet_view.showGridLines = False

    thin = Side(style="thin", color="BFBFBF")
    med = Side(style="medium", color="808080")
    thin_border = Border(left=thin, right=thin, top=thin, bottom=thin)
    top_border = Border(left=thin, right=thin, top=med, bottom=thin)

    # Title + period parameters.
    ws["B1"] = "Отчёт о движении денежных средств" + (" (тыс. руб.)" if thousands else "")
    ws["B1"].font = Font(bold=True, size=14)
    ws["C1"], ws["D1"], ws["E1"], ws["F1"] = "Месяц", month, "Год", year
    ws["C1"].font = ws["E1"].font = Font(bold=True)

    # Header row (3): «Статья» + the 8 comparison columns.
    head_cell = ws.cell(row=3, column=2, value="Статья")
    head_cell.font = Font(bold=True, color="FFFFFF")
    head_cell.fill = _HEADER_FILL
    head_cell.alignment = Alignment(vertical="center")
    head_cell.border = thin_border
    for i, head in enumerate(_HEADERS):
        cell = ws.cell(row=3, column=3 + i, value=head)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        cell.border = thin_border
    ws.row_dimensions[3].height = 30

    r = 4
    for row in rows:
        kind = row["kind"]
        bold = kind in _BOLD_KINDS
        fill = _ROW_FILLS.get(kind)
        border = top_border if kind in ("saldo", "total") else thin_border

        label = ws.cell(row=r, column=2, value=row["label"])
        label.font = Font(bold=bold)
        label.alignment = Alignment(indent=row["depth"], vertical="center")
        for col in range(2, _LAST_COL + 1):
            cell = ws.cell(row=r, column=col)
            cell.border = border
            if fill is not None:
                cell.fill = fill

        if row["cols"]:
            for i, key in enumerate(_COL_KEYS):
                v = row["cols"][key]
                cell = ws.cell(row=r, column=3 + i)
                if v is not None:
                    is_pct = key in ("pct_m", "pct_y")
                    cell.value = v if is_pct else float(v)
                    cell.number_format = _PCT_FMT if is_pct else _NUM_FMT
                cell.alignment = Alignment(horizontal="right", vertical="center")
                if bold:
                    cell.font = Font(bold=True)
        r += 1

    ws.column_dimensions["A"].width = 3.4
    ws.column_dimensions["B"].width = 54
    for col in "CDEFGHIJ":
        ws.column_dimensions[col].width = 14
    ws.freeze_panes = "C4"

    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue()


# Flat document-list export: (header, CashflowDocument attribute, column width).
# "_income"/"_outflow" split the signed amount into the two money columns.
_DOC_COLUMNS = [
    ("Дата", "date", 12),
    ("Номер", "number", 16),
    ("Вид документа", "doc_type", 26),
    ("Вид операции", "operation_type", 28),
    ("Движение", "direction", 13),
    ("Источник", "source", 10),
    ("Организация", "organization", 26),
    ("Контрагент", "counterparty", 28),
    ("Статья", "article", 28),
    ("Поступление", "_income", 14),
    ("Расход", "_outflow", 14),
    ("Назначение", "purpose", 40),
    ("Комментарий", "comment", 40),
    ("Заметка", "note", 22),
]


def build_cashflow_documents_xlsx(month, year):
    """Return the flat list of 1С cash-flow documents for month+year as .xlsx bytes.

    Unlike :func:`build_cashflow_odds_xlsx` (the aggregated statement), this is the
    raw ledger: every ``CashflowDocument`` of the month, with the amount split into
    «Поступление»/«Расход» columns and an «Итого» row that ties to the report."""
    from .models import CashflowDocument

    date_from = datetime.date(year, month, 1)
    date_to = _last_day(year, month)
    docs = (
        CashflowDocument.objects
        .filter(date__gte=date_from, date__lte=date_to)
        .order_by("date", "number")
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Документы"
    ws.sheet_view.showGridLines = False

    thin = Side(style="thin", color="BFBFBF")
    med = Side(style="medium", color="808080")
    thin_border = Border(left=thin, right=thin, top=thin, bottom=thin)
    total_border = Border(left=thin, right=thin, top=med, bottom=thin)
    ncols = len(_DOC_COLUMNS)
    inc_idx = next(i for i, c in enumerate(_DOC_COLUMNS, start=1) if c[1] == "_income")
    out_idx = next(i for i, c in enumerate(_DOC_COLUMNS, start=1) if c[1] == "_outflow")

    # Title + period.
    ws.cell(row=1, column=1, value="Движение денежных средств — список документов").font = Font(bold=True, size=14)
    ws.cell(row=2, column=1, value=f"{_MONTHS_RU[month]} {year}").font = Font(bold=True)

    # Header (row 3).
    for i, (head, _attr, _w) in enumerate(_DOC_COLUMNS, start=1):
        cell = ws.cell(row=3, column=i, value=head)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        cell.border = thin_border
    ws.row_dimensions[3].height = 26

    income_total = Decimal(0)
    outflow_total = Decimal(0)
    r = 4
    for doc in docs:
        is_income = doc.is_income
        amt = doc.amount or Decimal(0)
        if is_income:
            income_total += amt
        else:
            outflow_total += amt
        values = {
            "date": doc.date, "number": doc.number, "doc_type": doc.doc_type,
            "operation_type": doc.operation_type,
            "direction": doc.direction, "source": doc.source,
            "organization": doc.organization, "counterparty": doc.counterparty,
            "article": doc.article, "purpose": doc.purpose,
            "comment": doc.comment, "note": doc.note,
            "_income": float(amt) if is_income else None,
            "_outflow": None if is_income else float(amt),
        }
        for i, (_head, attr, _w) in enumerate(_DOC_COLUMNS, start=1):
            cell = ws.cell(row=r, column=i)
            cell.border = thin_border
            v = values[attr]
            if attr in ("_income", "_outflow"):
                if v is not None:
                    cell.value = v
                    cell.number_format = _NUM_FMT
                cell.alignment = Alignment(horizontal="right", vertical="center")
            elif attr == "date":
                cell.value = v
                cell.number_format = "DD.MM.YYYY"
                cell.alignment = Alignment(vertical="center")
            else:
                cell.value = v
                cell.alignment = Alignment(vertical="center", wrap_text=attr in ("purpose", "comment"))
        r += 1

    # «Итого» row: sums of the money columns (ties to the report's netto).
    for col in range(1, ncols + 1):
        cell = ws.cell(row=r, column=col)
        cell.border = total_border
        cell.font = Font(bold=True)
    ws.cell(row=r, column=1, value="Итого")
    ic = ws.cell(row=r, column=inc_idx, value=float(income_total))
    oc = ws.cell(row=r, column=out_idx, value=float(outflow_total))
    for cell in (ic, oc):
        cell.number_format = _NUM_FMT
        cell.alignment = Alignment(horizontal="right")
        cell.font = Font(bold=True)

    for i, (_head, _attr, width) in enumerate(_DOC_COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = "A4"
    if r > 4:  # header + data rows only (exclude the «Итого» row from the filter)
        ws.auto_filter.ref = f"A3:{get_column_letter(ncols)}{r - 1}"

    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue()
