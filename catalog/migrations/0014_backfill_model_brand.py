from django.db import migrations


def backfill(apps, schema_editor):
    """Assign each model to its products' brand; split models shared across
    several brands into one model per brand."""
    ModelProduct = apps.get_model("catalog", "ModelProduct")
    Product = apps.get_model("catalog", "Product")

    for mp in list(ModelProduct.objects.all()):
        # Dedup in Python: .distinct() can't be trusted here because Product's
        # Meta.ordering leaks extra columns into the DISTINCT clause.
        brand_ids = sorted(
            {
                b
                for b in Product.objects.filter(model_product=mp).values_list(
                    "brand_id", flat=True
                )
                if b is not None
            }
        )
        if not brand_ids:
            continue  # model used by no product -> leave brand empty
        mp.brand_id = brand_ids[0]
        mp.save()
        # Give every additional brand its own copy of the model.
        for bid in brand_ids[1:]:
            copy = ModelProduct.objects.create(name=mp.name, brand_id=bid)
            Product.objects.filter(model_product=mp, brand_id=bid).update(
                model_product=copy
            )


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0013_modelproduct_brand_alter_modelproduct_name_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
