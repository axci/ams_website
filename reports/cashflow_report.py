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
from openpyxl.styles import Alignment, Font

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


def build_rows(month, year):
    """Return ``(rows, unmapped)``: the statement as a flat ordered list of
    {label, depth, kind, cols} (cols None for section headers), and the sorted
    list of article names seen in the data but not mapped to any report line."""
    mapping = effective_mapping()
    unmapped = set()

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
        return "" if v == 0 else f"{v:,.0f}".replace(",", " ")

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
                "cur": c, "prev": d, "diff_m": c - d, "pct_m": pm,
                "ytd": g, "pytd": h, "diff_y": g - h, "pct_y": py,
                # display strings (HTML); the .xlsx uses the raw values above.
                "cur_disp": _money(c), "prev_disp": _money(d),
                "diff_m_disp": _money(c - d), "pct_m_disp": _pct(pm),
                "ytd_disp": _money(g), "pytd_disp": _money(h),
                "diff_y_disp": _money(g - h), "pct_y_disp": _pct(py),
            }
        out.append({"label": r["label"], "depth": r["depth"], "kind": r["kind"], "cols": cols})
    return out, sorted(unmapped)


_COL_KEYS = ("cur", "prev", "diff_m", "pct_m", "ytd", "pytd", "diff_y", "pct_y")
_HEADERS = ["месяц текущий", "месяц год назад", " +/-", "%",
            "с начала года", "с начала предыдущего года", " +/-", "%"]
_BOLD_KINDS = {"sec", "grp", "sub", "saldo", "total"}


def build_cashflow_odds_xlsx(month, year):
    """Return the ОДДС for month+year as .xlsx bytes, matching the template."""
    rows, _unmapped = build_rows(month, year)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "cf"

    ws["B1"] = "Отчёт о движении денежных средств"
    ws["B1"].font = Font(bold=True, size=13)
    ws["C1"], ws["D1"], ws["E1"], ws["F1"] = "Месяц", month, "Год", year
    for i, head in enumerate(_HEADERS):
        cell = ws.cell(row=3, column=3 + i, value=head)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical="center")

    r = 4
    for row in rows:
        bold = row["kind"] in _BOLD_KINDS
        label = ws.cell(row=r, column=2, value=row["label"])
        label.font = Font(bold=bold)
        label.alignment = Alignment(indent=row["depth"])
        if row["cols"]:
            for i, key in enumerate(_COL_KEYS):
                v = row["cols"][key]
                if v is None:
                    continue
                cell = ws.cell(row=r, column=3 + i)
                is_pct = key in ("pct_m", "pct_y")
                cell.value = v if is_pct else float(v)
                cell.number_format = "0%" if is_pct else "#,##0"
                if bold:
                    cell.font = Font(bold=True)
        r += 1

    ws.column_dimensions["A"].width = 3.4
    ws.column_dimensions["B"].width = 54
    for col in "CDEFGHIJ":
        ws.column_dimensions[col].width = 13
    ws.freeze_panes = "C4"

    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue()
