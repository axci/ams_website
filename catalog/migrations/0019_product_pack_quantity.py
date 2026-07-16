from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0018_brand_hidden_warehouses"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="pack_quantity",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="Сколько штук товара в одной упаковке.",
                null=True,
                verbose_name="количество штук в упаковке",
            ),
        ),
    ]
