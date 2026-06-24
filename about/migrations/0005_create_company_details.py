from django.db import migrations


def create_company(apps, schema_editor):
    # Create the singleton record, pre-filled from the model field defaults.
    CompanyDetails = apps.get_model("about", "CompanyDetails")
    CompanyDetails.objects.get_or_create(pk=1)


def remove_company(apps, schema_editor):
    apps.get_model("about", "CompanyDetails").objects.filter(pk=1).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("about", "0004_companydetails"),
    ]

    operations = [
        migrations.RunPython(create_company, remove_company),
    ]
