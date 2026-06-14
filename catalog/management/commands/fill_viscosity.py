"""Fill Product.viscosity from the product name.

Extracts the SAE grade (e.g. "5W/30", "0W-20", "10W40") and stores it without
separators: 5W30, 0W20, 10W40.

    python manage.py fill_viscosity            # fill products with empty viscosity
    python manage.py fill_viscosity --dry-run  # preview only
    python manage.py fill_viscosity --overwrite  # also re-fill non-empty ones
"""

import re

from django.core.management.base import BaseCommand

from catalog.models import Product

# e.g. "5W30", "5W-30", "5W/30", "0W 20", "75W90"
VISCOSITY_RE = re.compile(r"\b(\d{1,2})W[\s\-/]?(\d{1,3})\b", re.IGNORECASE)


def extract_viscosity(name):
    match = VISCOSITY_RE.search(name or "")
    if not match:
        return ""
    return f"{match.group(1)}W{match.group(2)}"


class Command(BaseCommand):
    help = "Fill Product.viscosity from the product name (symbol-free, e.g. 5W30)."

    def add_arguments(self, parser):
        parser.add_argument("--overwrite", action="store_true",
                            help="Also overwrite products that already have a viscosity.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Show what would change without saving.")

    def handle(self, *args, **options):
        qs = Product.objects.all()
        if not options["overwrite"]:
            qs = qs.filter(viscosity="")

        to_update, samples = [], []
        for product in qs:
            viscosity = extract_viscosity(product.name)
            if viscosity and viscosity != product.viscosity:
                product.viscosity = viscosity
                to_update.append(product)
                if len(samples) < 12:
                    samples.append((product.sku, viscosity, product.name[:55]))

        verb = "Would update" if options["dry_run"] else "Updated"
        if not options["dry_run"] and to_update:
            Product.objects.bulk_update(to_update, ["viscosity"])

        self.stdout.write(self.style.SUCCESS(f"{verb} {len(to_update)} product(s)."))
        for sku, viscosity, name in samples:
            self.stdout.write(f"  {sku}: {viscosity:7} ← {name}")
        distinct = sorted({p.viscosity for p in to_update})
        self.stdout.write(f"Distinct viscosities: {distinct}")
