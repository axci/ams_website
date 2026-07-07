from django.db import migrations


def backfill(apps, schema_editor):
    """Create one Company per user from the buyer fields currently on User."""
    User = apps.get_model("accounts", "User")
    Company = apps.get_model("accounts", "Company")
    for u in User.objects.all():
        has_data = bool(
            u.code or u.inn or u.kpp or u.address or u.company_name or u.phone
            or (u.debt and u.debt != 0)
        )
        if not has_data:
            continue
        Company.objects.create(
            user=u,
            code=u.code or None,
            type=u.type or "legal",
            inn=u.inn or "",
            kpp=u.kpp or "",
            address=u.address or "",
            debt=u.debt or 0,
            company_name=u.company_name or "",
            phone=u.phone or "",
        )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0009_company_deliveryaddress"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
