"""Update Company debt from the 1C (УНФ) debts HTTP service.

The service returns a JSON array like::

    [{"code": "НФ-025663", "name": "ПИОНЕР ООО", "debt": 177053.66}, ...]

Each Company is matched by ``code`` and its ``debt`` updated. Companies whose
code is not in our database are skipped (never created). Like the product sync
this must run from a machine on the office LAN.

Configuration (CLI args override environment variables)::

    ERP_DEBTS_URL   --url        e.g. http://192.168.0.10/UNF3/hs/test/debts
    ERP_USER        --user       basic-auth user
    ERP_PASSWORD    --password   basic-auth password
"""

import base64
import json
import os
import urllib.request
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.utils import OperationalError

from accounts.models import Company

CENTS = Decimal("0.01")


class Command(BaseCommand):
    help = "Update Company debt from the 1C (УНФ) debts service (match by code)."

    def add_arguments(self, parser):
        parser.add_argument("--url", default=os.environ.get("ERP_DEBTS_URL"))
        parser.add_argument("--user", default=os.environ.get("ERP_USER"))
        parser.add_argument("--password", default=os.environ.get("ERP_PASSWORD"))
        parser.add_argument(
            "--file", help="Read JSON from a local file instead of fetching the URL."
        )
        parser.add_argument("--timeout", type=int, default=60)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing to the database.",
        )

    def handle(self, *args, **opts):
        data = self._load(opts)
        if not isinstance(data, list):
            raise CommandError("Expected a JSON array of debts.")

        # Desired debt per code (last row wins); skip empty/invalid numbers.
        want = {}
        errors = 0
        for row in data:
            code = str(row.get("code") or "").strip()
            raw = row.get("debt")
            if not code or raw is None or raw == "":
                continue
            try:
                want[code] = Decimal(str(raw)).quantize(CENTS, rounding=ROUND_HALF_UP)
            except (InvalidOperation, ValueError, TypeError):
                errors += 1
                self.stderr.write(f"{code}: неверное значение долга {raw!r}")

        companies = {c.code: c for c in Company.objects.filter(code__in=list(want))}
        changed = []
        for code, debt in want.items():
            company = companies.get(code)
            if company is not None and company.debt != debt:
                company.debt = debt
                changed.append(company)

        dry = opts["dry_run"]
        if changed and not dry:
            self._write(changed)

        skipped = len(want) - len(companies)  # feed codes not in our DB
        mode = "DRY RUN — ничего не записано" if dry else "готово"
        style = self.style.WARNING if (errors or dry) else self.style.SUCCESS
        self.stdout.write(
            style(
                f"Синхронизация долгов ({mode}): обновлено {len(changed)}, "
                f"без изменений {len(companies) - len(changed)}, "
                f"не найдено {skipped}, ошибок {errors}."
            )
        )

    def _write(self, companies):
        """One bulk UPDATE, reconnecting once if the connection drops."""
        for attempt in (1, 2):
            try:
                with transaction.atomic():
                    Company.objects.bulk_update(companies, ["debt"], batch_size=500)
                return
            except OperationalError:
                connection.close()
                if attempt == 2:
                    raise

    def _load(self, opts):
        if opts.get("file"):
            with open(opts["file"], encoding="utf-8") as fh:
                return json.load(fh)
        url = opts.get("url")
        if not url:
            raise CommandError("Укажите --url (или переменную ERP_DEBTS_URL), либо --file.")
        req = urllib.request.Request(url)
        user, password = opts.get("user"), opts.get("password")
        if user and password is not None:
            cred = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
            req.add_header("Authorization", f"Basic {cred}")
        try:
            with urllib.request.urlopen(req, timeout=opts["timeout"]) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise CommandError(f"Не удалось получить данные с {url}: {exc}")
