from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0015_alter_product_viscosity_alter_product_volume_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="product",
            name="article",
            field=models.CharField(
                blank=True, db_index=True, max_length=64, verbose_name="артикул"
            ),
        ),
    ]
