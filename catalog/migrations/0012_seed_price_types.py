from django.db import migrations


PRICE_TYPES = [
    # name, order, is_public, is_default
    ("Розничные", 1, True, False),
    ("Мелкий ОПТ", 2, False, False),
    ("Крупный ОПТ", 3, False, True),
]


def seed(apps, schema_editor):
    PriceType = apps.get_model("catalog", "PriceType")
    for name, order, is_public, is_default in PRICE_TYPES:
        PriceType.objects.get_or_create(
            name=name,
            defaults={"order": order, "is_public": is_public, "is_default": is_default},
        )


def unseed(apps, schema_editor):
    PriceType = apps.get_model("catalog", "PriceType")
    PriceType.objects.filter(name__in=[p[0] for p in PRICE_TYPES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0011_pricetype_productprice_and_more"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
