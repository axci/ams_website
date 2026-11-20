"""Export the cashflow report to an .xlsx workbook (admin-only)."""

from io import BytesIO

import openpyxl
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

# Header, getter. One row per document.
COLUMNS = [
    ("Дата", lambda d: d.date),
    ("Номер", lambda d: d.number),
    ("Движение", lambda d: d.direction),
    ("Источник", lambda d: d.source),
    ("Вид документа", lambda d: d.doc_type),
    ("Сумма", lambda d: float(d.amount)),
    ("Организация", lambda d: d.organization),
    ("Контрагент", lambda d: d.counterparty),
    ("Статья", lambda d: d.article),
    ("Комментарий", lambda d: d.comment),
    ("Назначение", lambda d: d.purpose),
    ("Заметка", lambda d: d.note),
]
_AMOUNT_COL = 6  # index of «Сумма» (1-based)
_WIDTHS = [12, 16, 14, 10, 22, 16, 30, 30, 26, 32, 32, 26]


def build_cashflow_xlsx(documents, totals=None, date_from=None, date_to=None):
    """Return the cashflow report as .xlsx bytes: a title, the documents, totals.

    ``documents`` is any iterable of CashflowDocument (an iterator is fine)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Денежный поток"

    period = ""
    if date_from or date_to:
        period = f"  (период: {date_from or '…'} — {date_to or '…'})"
    title = ws.cell(row=1, column=1, value="Движение денежных средств" + period)
    title.font = Font(bold=True, size=13)
    ws.append([])  # blank row 2

    headers = [t for t, _ in COLUMNS]
    ws.append(headers)
    header_row = ws.max_row
    for cell in ws[header_row]:
        cell.font = Font(bold=True)
    ws.freeze_panes = f"A{header_row + 1}"  # a string, so it doesn't touch a cell

    for d in documents:
        ws.append([get(d) for _, get in COLUMNS])

    if totals is not None:
        ws.append([])
        label = ws.cell(
            row=ws.max_row + 1, column=1,
            value=f"Итого за период — документов: {totals['count']}",
        )
        label.font = Font(bold=True)
        ws.append(["Поступление", "", "", "", "", float(totals["income"])])
        ws.append(["Расход", "", "", "", "", float(totals["outflow"])])
        ws.append(["Сальдо", "", "", "", "", float(totals["net"])])

    for row in range(header_row + 1, ws.max_row + 1):
        ws.cell(row=row, column=_AMOUNT_COL).number_format = "#,##0.00"
    for idx, width in enumerate(_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width

    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue()
