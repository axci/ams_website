from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0016_alter_product_article"),
        ("warehouses", "0006_warehouse_phone"),
    ]

    operations = [
        migrations.AddField(
            model_name="brand",
            name="warehouses",
            field=models.ManyToManyField(
                blank=True,
                help_text="Склады, для которых виден бренд (пусто = все склады).",
                related_name="brands",
                to="warehouses.warehouse",
            ),
        ),
    ]
