from django.db import migrations

# Inter-warehouse transit warehouse name -> stable unique code.
TRANSIT_CODES = {
    "Склад транзит Кемерово-Нкз (АМС)": "TRANSIT-KEM-NVK",
    "Склад транзит Новосибирск-Нкз (АМС)": "TRANSIT-NSK-NVK",
    "Склад транзит Кемерово-Новосибирск (АМС)": "TRANSIT-KEM-NSK",
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
        ("warehouses", "0007_transit_warehouses"),
    ]

    operations = [
        migrations.RunPython(create_transit, remove_transit),
    ]
