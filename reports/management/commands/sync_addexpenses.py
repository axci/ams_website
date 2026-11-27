"""Fetch «Дополнительные расходы» documents from the 1С (УНФ) HTTP service.

The freight/landed-cost side of the profit report: extra costs (e.g.
«Транспортные услуги») booked against earlier goods receipts. Like
``sync_receipts`` this runs office-side (1С is unreachable from the VPS) and
writes to the site DB over the tunnel; the admin reads the stored rows. Config:
``settings.ADDEXPENSES_1C`` (URL / optional HTTP Basic auth, reusing ERP_* by
default).

Each document carries two line arrays: ``expenses`` (the cost itself — what
``amount`` totals) and ``items`` (the receipt goods the cost is distributed
over, each naming its receipt in ``receiptDoc``). ``number`` is reused across
documents (only ``(number, date)`` is unique) and there is no stable id, so the
sync does a full refresh (delete + bulk_create) rather than upserting.
"""
import json
import re
import urllib.error
import urllib.request
from base64 import b64encode
from datetime import date
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_date

from reports.models import AddExpense, AddExpenseLine

# «Приходная накладная 5886 (вх. УТ-3532) от 26.11.2026» → short number + date.
# The short number is the receipt's number without the «00НФ-» prefix and leading
# zeros; 1С zero-pads it to 6 digits (verified against the full receipts feed —
# 810/811 refs match «00НФ-»+zfill(6)+date; the lone miss is «(не проведён)»).
_RECEIPT_PREFIX = "00НФ-"
_RECEIPT_PAD = 6
_RECEIPT_DOC_RE = re.compile(r"(\d+)\s*(?:\([^)]*\))?\s*от\s+(\d{2})\.(\d{2})\.(\d{4})")


def _text(value, limit=None):
    text = "" if value is None else str(value).strip()
    return text[:limit] if limit else text


def _dec(value):
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def parse_receipt_doc(text):
    """«Приходная накладная 5886 (вх. УТ-3532) от 26.11.2026»
    → ("00НФ-005886", date(2026, 11, 26)). ("", None) when it can't be parsed.

    Reconstructs the receipt number so a goods line can be joined to
    :class:`Receipt` on (number, date) — both tables full-refresh independently,
    so the link is kept as stored values, not a FK.
    """
    if not text:
        return "", None
    m = _RECEIPT_DOC_RE.search(text)
    if not m:
        return "", None
    num, dd, mm, yyyy = m.groups()
    try:
        d = date(int(yyyy), int(mm), int(dd))
    except ValueError:
        d = None
    return _RECEIPT_PREFIX + num.zfill(_RECEIPT_PAD), d


def build_objects(rows):
    """Parse feed rows into ``[(AddExpense, [line-kwargs, ...]), ...]`` and a skip count.

    Pure (no DB): the lines are kwargs dicts, turned into :class:`AddExpenseLine`
    objects in :meth:`Command.handle` once the documents have primary keys. The
    goods lines (``items``) carry ``receipt_doc``; the cost lines (``expenses``)
    do not. Neither carries a price in this feed.
    """
    pairs = []
    skipped = 0
    for row in rows:
        if not isinstance(row, dict):
            skipped += 1
            continue
        number = _text(row.get("number"), 32)
        date = parse_date(_text(row.get("date")))
        if not number or date is None:
            skipped += 1
            continue
        document = AddExpense(
            number=number,
            date=date,
            organization=_text(row.get("organization"), 128),
            counterparty=_text(row.get("counterparty"), 255),
            amount=_dec(row.get("amount")),
        )
        lines = []
        # items = goods the cost is spread over (keep receiptDoc); expenses = the cost.
        for is_expense, key in ((False, "items"), (True, "expenses")):
            for line in (row.get(key) or []):
                if not isinstance(line, dict):
                    continue
                receipt_doc = _text(line.get("receiptDoc"), 255)
                receipt_number, receipt_date = parse_receipt_doc(receipt_doc)
                lines.append({
                    "is_expense": is_expense,
                    "receipt_doc": receipt_doc,
                    "receipt_number": receipt_number,
                    "receipt_date": receipt_date,
                    "product": _text(line.get("product"), 255),
                    "quantity": _dec(line.get("quantity")),
                    "line_sum": _dec(line.get("sum")),
                })
        pairs.append((document, lines))
    return pairs, skipped


class Command(BaseCommand):
    help = "Загрузить документы «Дополнительные расходы» из 1С (УНФ) в БД сайта."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Не писать в БД — только показать, что было бы загружено.",
        )

    def handle(self, *args, **opts):
        cfg = getattr(settings, "ADDEXPENSES_1C", {}) or {}
        url = (cfg.get("URL") or "").strip()
        if not url:
            raise CommandError("ADDEXPENSES_1C_URL не задан (см. .env).")

        rows = self._fetch(url, cfg)
        if not isinstance(rows, list):
            raise CommandError("Ожидался JSON-массив документов доп. расходов от 1С.")

        pairs, skipped = build_objects(rows)
        n_lines = sum(len(lines) for _d, lines in pairs)

        if opts["dry_run"]:
            self.stdout.write(self.style.SUCCESS(
                f"Готово (dry-run): получено {len(rows)}, разобрано {len(pairs)} "
                f"документов / {n_lines} строк, пропущено {skipped}. В БД ничего не записано."
            ))
            return

        with transaction.atomic():
            AddExpenseLine.objects.all().delete()
            AddExpense.objects.all().delete()
            AddExpense.objects.bulk_create([d for d, _lines in pairs], batch_size=500)
            lines = [
                AddExpenseLine(document=document, **kw)
                for document, line_kwargs in pairs
                for kw in line_kwargs
            ]
            AddExpenseLine.objects.bulk_create(lines, batch_size=1000)
        self.stdout.write(self.style.SUCCESS(
            f"Готово: получено {len(rows)}, загружено {len(pairs)} документов / "
            f"{len(lines)} строк, пропущено {skipped} (таблица обновлена)."
        ))

    def _fetch(self, url, cfg):
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        user = (cfg.get("USER") or "").strip()
        if user:
            token = b64encode(f"{user}:{cfg.get('PASSWORD') or ''}".encode("utf-8")).decode("ascii")
            req.add_header("Authorization", "Basic " + token)
        timeout = int(cfg.get("TIMEOUT") or 120)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raise CommandError(f"1С вернула ошибку HTTP {exc.code}: {exc.reason}")
        except urllib.error.URLError as exc:
            raise CommandError(f"Не удалось подключиться к 1С ({url}): {exc.reason}")
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"Ошибка запроса к 1С: {exc}")
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"Некорректный JSON из 1С: {exc}")
