from django.db import migrations

# Transit warehouse name -> stable unique code.
TRANSIT_CODES = {
    "Оптовый КемеровоТранзит (товар поставщиков в пути)(АМС)": "TRANSIT-KEM",
    "Новокузнецк Транзит (АМС)": "TRANSIT-NVK",
    "Склад Новосибирск Транзит (АМС)": "TRANSIT-NSK",
}


def create_transit(apps, schema_editor):
    Warehouse = apps.get_model("warehouses", "Warehouse")
    for name, code in TRANSIT_CODES.items():
        Warehouse.objects.update_or_create(
            code=code, defaults={"name": name, "is_active": False},
        )


def remove_transit(apps, schema_editor):
    Warehouse = apps.get_model("warehouses", "Warehouse")
    Warehouse.objects.filter(code__in=TRANSIT_CODES.values()).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("warehouses", "0006_warehouse_phone"),
    ]

    operations = [
        migrations.RunPython(create_transit, remove_transit),
    ]
