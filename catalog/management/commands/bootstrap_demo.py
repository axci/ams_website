"""Populate a throwaway demo instance (e.g. Render free tier).

Loads the baked catalog fixture, copies the baked product/banner images into
MEDIA_ROOT, and ensures known demo logins. Safe to run repeatedly.
Triggered from the container entrypoint when SEED_DEMO is set.
"""

import os
import shutil

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

from accounts.models import User
from warehouses.models import Warehouse


class Command(BaseCommand):
    help = "Load demo catalog data + media and create demo logins."

    def handle(self, *args, **options):
        fixture = settings.BASE_DIR / "deploy" / "demo_data.json"
        if fixture.exists():
            call_command("loaddata", str(fixture))
            self.stdout.write(f"Loaded {fixture.name}.")
        else:
            self.stdout.write(self.style.WARNING(f"No fixture at {fixture}."))

        media_src = settings.BASE_DIR / "deploy" / "demo_media"
        if media_src.exists():
            shutil.copytree(media_src, settings.MEDIA_ROOT, dirs_exist_ok=True)
            self.stdout.write("Copied demo media.")

        admin_pw = os.environ.get("DEMO_ADMIN_PASSWORD", "demo12345")
        buyer_pw = os.environ.get("DEMO_BUYER_PASSWORD", "demo12345")

        admin, _ = User.objects.get_or_create(
            username="admin", defaults={"email": "admin@example.com"}
        )
        admin.is_staff = True
        admin.is_superuser = True
        admin.set_password(admin_pw)
        admin.save()

        buyer, _ = User.objects.get_or_create(
            username="buyer",
            defaults={"email": "buyer@example.com", "company_name": "Demo Buyer"},
        )
        buyer.set_password(buyer_pw)
        buyer.save()
        # Assign every warehouse so the demo buyer can see stock anywhere.
        buyer.warehouses.set(Warehouse.objects.all())

        self.stdout.write(self.style.SUCCESS("Demo bootstrap complete."))
        self.stdout.write(f"  admin / {admin_pw}  (staff)")
        self.stdout.write(f"  buyer / {buyer_pw}  (buyer)")
