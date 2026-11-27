"""Fetch goods receipts from the 1С (УНФ) HTTP service into the site DB.

The cost side of the profit report. Like `sync_cashflow`, 1С is on the office LAN
(unreachable from the VPS) so this runs office-side (writing to the site DB over
the tunnel); the admin then reads the stored rows. Config: ``settings.RECEIPTS_1C``
(URL / optional HTTP Basic auth, reusing the ERP_* creds by default).

The feed returns the FULL set each time; ``number`` is reused across documents
(only ``(number, date)`` is unique) and there is no stable id, so the sync does a
full refresh (delete + bulk_create) rather than upserting — mirroring 1С exactly.
"""
import json
import urllib.error
import urllib.request
from base64 import b64encode
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_date

from reports.models import Receipt, ReceiptLine


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


def build_objects(rows):
    """Parse feed rows into ``[(Receipt, [line-kwargs, ...]), ...]`` and a skip count.

    Pure (no DB): the lines are kwargs dicts, turned into :class:`ReceiptLine`
    objects in :meth:`Command.handle` once the receipts have primary keys.
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
        receipt = Receipt(
            number=number,
            date=date,
            organization=_text(row.get("organization"), 128),
            counterparty=_text(row.get("counterparty"), 255),
            operation_type=_text(row.get("operationType"), 64),
            warehouse=_text(row.get("warehouse"), 128),
            amount=_dec(row.get("amount")),
        )
        lines = []
        for is_expense, key in ((False, "items"), (True, "expenses")):
            for line in (row.get(key) or []):
                if not isinstance(line, dict):
                    continue
                lines.append({
                    "is_expense": is_expense,
                    "product": _text(line.get("product"), 255),
                    "quantity": _dec(line.get("quantity")),
                    "price": _dec(line.get("price")),
                    "line_sum": _dec(line.get("sum")),
                })
        pairs.append((receipt, lines))
    return pairs, skipped


class Command(BaseCommand):
    help = "Загрузить поступления товаров (закупки/возвраты) из 1С (УНФ) в БД сайта."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Не писать в БД — только показать, что было бы загружено.",
        )

    def handle(self, *args, **opts):
        cfg = getattr(settings, "RECEIPTS_1C", {}) or {}
        url = (cfg.get("URL") or "").strip()
        if not url:
            raise CommandError("RECEIPTS_1C_URL не задан (см. .env).")

        rows = self._fetch(url, cfg)
        if not isinstance(rows, list):
            raise CommandError("Ожидался JSON-массив поступлений от 1С.")

        pairs, skipped = build_objects(rows)
        n_lines = sum(len(lines) for _r, lines in pairs)

        if opts["dry_run"]:
            self.stdout.write(self.style.SUCCESS(
                f"Готово (dry-run): получено {len(rows)}, разобрано {len(pairs)} "
                f"поступлений / {n_lines} строк, пропущено {skipped}. В БД ничего не записано."
            ))
            return

        with transaction.atomic():
            ReceiptLine.objects.all().delete()
            Receipt.objects.all().delete()
            Receipt.objects.bulk_create([r for r, _lines in pairs], batch_size=500)
            lines = [
                ReceiptLine(receipt=receipt, **kw)
                for receipt, line_kwargs in pairs
                for kw in line_kwargs
            ]
            ReceiptLine.objects.bulk_create(lines, batch_size=1000)
        self.stdout.write(self.style.SUCCESS(
            f"Готово: получено {len(rows)}, загружено {len(pairs)} поступлений / "
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
