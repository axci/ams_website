"""Upload local MEDIA_ROOT files to the configured object storage (R2/S3).

Run locally with the storage env vars set so the default storage points at the
bucket, then this pushes your local media/ into it. Already-present files are
skipped unless --overwrite is given.

    AWS_STORAGE_BUCKET_NAME=... AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \\
    AWS_S3_ENDPOINT_URL=... AWS_S3_CUSTOM_DOMAIN=... \\
    python manage.py sync_media
"""

from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Upload local media/ files to the configured storage (R2/S3)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            default=None,
            help="Directory to upload from (default: MEDIA_ROOT).",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Re-upload files even if they already exist in the bucket.",
        )

    def handle(self, *args, **options):
        storage = storages["default"]
        backend = type(storage).__name__
        if "S3" not in backend:
            self.stderr.write(
                f"Default storage is {backend}, not S3/R2. Set the storage env "
                "vars (AWS_STORAGE_BUCKET_NAME, keys, endpoint) before running."
            )
            return

        root = Path(options["source"]) if options["source"] else Path(settings.MEDIA_ROOT)
        if not root.exists():
            self.stdout.write(f"Source directory {root} does not exist.")
            return

        uploaded = skipped = 0
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            key = path.relative_to(root).as_posix()
            exists = storage.exists(key)
            if exists and not options["overwrite"]:
                skipped += 1
                continue
            if exists:
                storage.delete(key)
            with open(path, "rb") as fh:
                storage.save(key, ContentFile(fh.read()))
            uploaded += 1
            if uploaded % 50 == 0:
                self.stdout.write(f"  …{uploaded} uploaded")

        self.stdout.write(
            self.style.SUCCESS(f"Done: {uploaded} uploaded, {skipped} already present.")
        )
