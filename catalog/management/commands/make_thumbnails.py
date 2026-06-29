"""Generate product thumbnails (picture_thumb) for the catalog grid.

Run after importing product images (locally, or in the Render Shell where R2 is
reachable):

    python manage.py make_thumbnails
"""

from django.core.management.base import BaseCommand

from catalog.models import Product


class Command(BaseCommand):
    help = "Generate missing product thumbnails."

    def add_arguments(self, parser):
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Regenerate even if a thumbnail already exists.",
        )

    def handle(self, *args, **options):
        qs = Product.objects.exclude(picture="").exclude(picture__isnull=True)
        done = skipped = failed = 0
        for product in qs.iterator():
            if product.picture_thumb and not options["overwrite"]:
                skipped += 1
                continue
            if product.picture_thumb:
                product.picture_thumb.delete(save=False)
            product.generate_thumbnail()
            if product.picture_thumb:
                product.save(update_fields=["picture_thumb"])
                done += 1
            else:
                failed += 1
            if (done + failed) and (done + failed) % 50 == 0:
                self.stdout.write(f"  …{done} generated")
        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {done} generated, {skipped} already had thumbs, {failed} failed."
            )
        )
