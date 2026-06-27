"""Bake the current local DB + media into deploy/ for the demo deployment.

The inverse of ``bootstrap_demo``: dumps the public content models to
``deploy/demo_data.json`` and copies ``MEDIA_ROOT`` into ``deploy/demo_media/``.
Commit and push afterwards — the next Render deploy re-seeds from these files.

    python manage.py bake_demo
    git add -A && git commit -m "Refresh demo data + media" && git push
"""

import shutil
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

# Public content only — accounts/orders are excluded so buyer/debt/order data
# never lands in the (public) repo.
DEMO_APPS = ["catalog", "warehouses", "news", "about"]


class Command(BaseCommand):
    help = "Dump demo data + media into deploy/ (then git commit & push)."

    def handle(self, *args, **options):
        fixture = settings.BASE_DIR / "deploy" / "demo_data.json"
        with open(fixture, "w", encoding="utf-8") as fh:
            call_command("dumpdata", *DEMO_APPS, indent=2, stdout=fh)
        self.stdout.write(f"Wrote {fixture}.")

        media_root = Path(settings.MEDIA_ROOT)
        dest = settings.BASE_DIR / "deploy" / "demo_media"
        if media_root.exists() and any(media_root.iterdir()):
            shutil.copytree(media_root, dest, dirs_exist_ok=True)
            self.stdout.write(f"Copied {media_root} -> {dest}.")
        else:
            self.stdout.write("No local media to copy.")

        self.stdout.write(self.style.SUCCESS(
            "Baked. Next: git add -A && git commit -m 'Refresh demo' && git push"
        ))
