"""Fetch cash-flow documents from the 1С (УНФ) HTTP service into the site DB.

1С lives on the office LAN (unreachable from the VPS), so this runs office-side
— like the ERP sync — writing to the site DB (over the tunnel). The admin report
(`reports.CashflowDocument`) then reads the stored rows. Config comes from
``settings.CASHFLOW_1C`` (URL / optional HTTP Basic auth), set in the environment.
"""
import json
import urllib.error
import urllib.request
from base64 import b64encode
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_date

from reports.models import CashflowDocument


def _text(value, limit=None):
    text = "" if value is None else str(value).strip()
    return text[:limit] if limit else text


def _amount(value):
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


class Command(BaseCommand):
    help = "Загрузить документы движения денежных средств из 1С (УНФ) в БД сайта."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Не писать в БД — только показать, что было бы загружено.",
        )

    def handle(self, *args, **opts):
        cfg = getattr(settings, "CASHFLOW_1C", {}) or {}
        url = (cfg.get("URL") or "").strip()
        if not url:
            raise CommandError("CASHFLOW_1C_URL не задан (см. .env).")

        rows = self._fetch(url, cfg)
        if not isinstance(rows, list):
            raise CommandError("Ожидался JSON-массив документов от 1С.")

        created = updated = skipped = 0
        for row in rows:
            if not isinstance(row, dict):
                skipped += 1
                continue
            number = _text(row.get("number"), 64)
            date = parse_date(_text(row.get("date")))
            if not number or date is None:
                skipped += 1
                continue
            defaults = {
                "date": date,
                "amount": _amount(row.get("amount")),
                "direction": _text(row.get("direction"), 32),
                "source": _text(row.get("source"), 32),
                "doc_type": _text(row.get("docType"), 128),
                "organization": _text(row.get("organization"), 255),
                "counterparty": _text(row.get("counterparty"), 255),
                "article": _text(row.get("article"), 255),
                "comment": _text(row.get("comment")),
                "purpose": _text(row.get("purpose")),
            }
            if opts["dry_run"]:
                continue
            _, is_created = CashflowDocument.objects.update_or_create(
                number=number, defaults=defaults,
            )
            created += int(is_created)
            updated += int(not is_created)

        verb = "получено" if opts["dry_run"] else "загружено"
        self.stdout.write(self.style.SUCCESS(
            f"Готово: {verb} {len(rows)}, создано {created}, обновлено {updated}, "
            f"пропущено {skipped}."
        ))

    def _fetch(self, url, cfg):
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        user = (cfg.get("USER") or "").strip()
        if user:
            token = b64encode(f"{user}:{cfg.get('PASSWORD') or ''}".encode("utf-8")).decode("ascii")
            req.add_header("Authorization", "Basic " + token)
        timeout = int(cfg.get("TIMEOUT") or 60)
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
