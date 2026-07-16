from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0017_brand_warehouses"),
        ("warehouses", "0006_warehouse_phone"),
    ]

    operations = [
        # Rename rather than drop/recreate, so any brand already configured in
        # the admin keeps its warehouses.
        migrations.RenameField(
            model_name="brand",
            old_name="warehouses",
            new_name="hidden_warehouses",
        ),
        migrations.AlterField(
            model_name="brand",
            name="hidden_warehouses",
            field=models.ManyToManyField(
                blank=True,
                help_text="Склады, на которых бренд скрыт (пусто = виден везде).",
                related_name="hidden_brands",
                to="warehouses.warehouse",
            ),
        ),
    ]
