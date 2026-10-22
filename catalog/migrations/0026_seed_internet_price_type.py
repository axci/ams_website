from django.db import migrations

# 1C (УНФ) started sending a "priceInternet" field; it maps to this price type.
NAME = "интернет-магазин"


def seed(apps, schema_editor):
    PriceType = apps.get_model("catalog", "PriceType")
    PriceType.objects.get_or_create(
        name=NAME,
        defaults={"order": 4, "is_public": False, "is_default": False},
    )


def unseed(apps, schema_editor):
    PriceType = apps.get_model("catalog", "PriceType")
    PriceType.objects.filter(name=NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0025_product_supplier"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
