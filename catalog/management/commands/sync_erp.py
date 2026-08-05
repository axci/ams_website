"""Update product prices and stock from the 1C (УНФ) products HTTP service.

The service returns a JSON array like::

    [{"code": "УТ000016035", "name": "...", "article": "...",
      "priceOpt": 3825, "priceRetail": 4618.21,
      "stockNovokuznetsk": 0, "stockKemerovo": 0, "stockNovosibirsk": 22}, ...]

Products are matched by ``code`` == ``Product.sku``. Only prices and stock are
touched — ``name`` and ``article`` are left untouched. Products whose code is
not found in the catalog are skipped (and reported).

The 1C service lives on the local network (e.g. http://192.168.0.10/...), so
this command must run from a machine on that LAN. To update the *production*
site, run it with ``DATABASE_URL`` pointing at the Timeweb Postgres through an
SSH tunnel — see ``deploy/sync_erp_cron.sh``.

Configuration (CLI args override environment variables)::

    ERP_PRODUCTS_URL   --url        e.g. http://192.168.0.10/UNF3/hs/test/products
    ERP_USER           --user       basic-auth user
    ERP_PASSWORD       --password   basic-auth password

Examples::

    python manage.py sync_erp --dry-run          # show what would change
    python manage.py sync_erp                     # apply
    python manage.py sync_erp --file sample.json  # from a saved file (testing)
"""

import base64
import json
import os
import urllib.request
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.utils import OperationalError

from catalog.models import PriceType, Product, ProductPrice
from warehouses.models import Stock, Warehouse

# JSON field -> price type name
PRICE_FIELDS = {
    "priceOpt": "Крупный ОПТ",
    "priceRetail": "Розничные",
}
# JSON field -> warehouse name
STOCK_FIELDS = {
    "stockNovosibirsk": "Новосибирск",
    "stockKemerovo": "Кемерово",
    "stockNovokuznetsk": "Новокузнецк",
}

CENTS = Decimal("0.01")


class Command(BaseCommand):
    help = "Update product prices and stock from the 1C (УНФ) products service."

    def add_arguments(self, parser):
        parser.add_argument("--url", default=os.environ.get("ERP_PRODUCTS_URL"))
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
            raise CommandError("Expected a JSON array of products.")

        price_types = self._resolve(PriceType, PRICE_FIELDS.values(), "тип цены")
        warehouses = self._resolve(Warehouse, STOCK_FIELDS.values(), "склад")

        dry = opts["dry_run"]
        skipped = errors = 0
        missing = []

        # Match every product in one query, then build the desired price/stock
        # state so it can be written in a couple of bulk upserts (few round-trips
        # = fast and resilient over a slow/unstable link).
        codes = [c for c in (str(r.get("code") or "").strip() for r in data) if c]
        products = {p.sku: p for p in Product.objects.filter(sku__in=codes)}

        want_prices = {}  # (product, price_type) -> price
        want_stock = {}   # (product, warehouse) -> quantity
        seen = set()
        for row in data:
            code = str(row.get("code") or "").strip()
            if not code:
                continue
            product = products.get(code)
            if product is None:
                skipped += 1
                if len(missing) < 20:
                    missing.append(code)
                continue
            try:
                prices, stocks = self._read_values(row)
            except (InvalidOperation, ValueError, TypeError) as exc:
                errors += 1
                self.stderr.write(f"{code}: {exc}")
                continue
            seen.add(product.pk)
            for pt_name, price in prices.items():
                want_prices[(product, price_types[pt_name])] = price
            for wh_name, qty in stocks.items():
                want_stock[(product, warehouses[wh_name])] = qty

        if not dry:
            self._write(want_prices, want_stock)
        updated = len(seen)

        mode = "DRY RUN — ничего не записано" if dry else "готово"
        style = self.style.WARNING if (errors or dry) else self.style.SUCCESS
        self.stdout.write(
            style(
                f"Синхронизация ({mode}): обновлено {updated}, "
                f"не найдено {skipped}, ошибок {errors}."
            )
        )
        if missing:
            more = "" if skipped <= len(missing) else f" …и ещё {skipped - len(missing)}"
            self.stdout.write("Коды не найдены: " + ", ".join(missing) + more)

    # -- helpers ---------------------------------------------------------------

    def _write(self, want_prices, want_stock):
        """Upsert all prices and stock in two bulk queries, reconnecting once if
        the database connection drops (slow/unstable links)."""
        for attempt in (1, 2):
            try:
                with transaction.atomic():
                    price_rows = [
                        ProductPrice(product=p, price_type=pt, price=price)
                        for (p, pt), price in want_prices.items()
                    ]
                    if price_rows:
                        ProductPrice.objects.bulk_create(
                            price_rows,
                            update_conflicts=True,
                            unique_fields=["product", "price_type"],
                            update_fields=["price"],
                            batch_size=500,
                        )
                    stock_rows = [
                        Stock(product=p, warehouse=w, quantity=qty)
                        for (p, w), qty in want_stock.items()
                    ]
                    if stock_rows:
                        Stock.objects.bulk_create(
                            stock_rows,
                            update_conflicts=True,
                            unique_fields=["product", "warehouse"],
                            update_fields=["quantity"],
                            batch_size=500,
                        )
                return
            except OperationalError:
                connection.close()  # drop the dead connection; retry reconnects
                if attempt == 2:
                    raise

    def _read_values(self, row):
        """Parse (and validate) the price/stock values from one JSON row."""
        prices = {}
        for field, pt_name in PRICE_FIELDS.items():
            val = row.get(field)
            if val is None or val == "":
                continue
            prices[pt_name] = Decimal(str(val)).quantize(CENTS, rounding=ROUND_HALF_UP)
        stocks = {}
        for field, wh_name in STOCK_FIELDS.items():
            val = row.get(field)
            if val is None or val == "":
                continue
            stocks[wh_name] = max(0, int(Decimal(str(val))))
        return prices, stocks

    def _resolve(self, model, names, label):
        by_name = {o.name.casefold(): o for o in model.objects.all()}
        resolved = {}
        for name in names:
            obj = by_name.get(name.casefold())
            if obj is None:
                raise CommandError(f"Не найден {label}: «{name}». Создайте его сначала.")
            resolved[name] = obj
        return resolved

    def _load(self, opts):
        if opts.get("file"):
            with open(opts["file"], encoding="utf-8") as fh:
                return json.load(fh)
        url = opts.get("url")
        if not url:
            raise CommandError(
                "Укажите --url (или переменную ERP_PRODUCTS_URL), либо --file."
            )
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
