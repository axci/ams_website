from django.db import migrations

GROUP_NAME = "Рассылка прайса"


def seed(apps, schema_editor):
    """Create the «Рассылка прайса» role: can open the price types and email a
    price list. Assign it to a staff user to let them send price lists."""
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    ct, _ = ContentType.objects.get_or_create(app_label="catalog", model="pricetype")
    # get_or_create so this is independent of post_migrate permission creation.
    view_perm, _ = Permission.objects.get_or_create(
        codename="view_pricetype",
        content_type=ct,
        defaults={"name": "Can view тип цены"},
    )
    send_perm, _ = Permission.objects.get_or_create(
        codename="send_price_list",
        content_type=ct,
        defaults={"name": "Может отправлять прайс-лист по email"},
    )
    group, _ = Group.objects.get_or_create(name=GROUP_NAME)
    group.permissions.add(view_perm, send_perm)


def unseed(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name=GROUP_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0027_alter_pricetype_options"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
