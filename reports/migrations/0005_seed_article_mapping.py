from django.db import migrations

# Starter overrides (editable later in admin → «Денежный поток: сопоставление статей»).
SEED = [
    # report_line must match a report line label exactly (see REPORT_LINES);
    # the «Прочие расходы» leaves are lower-case in the template.
    ("командировки", "представительские расходы"),
    ("личные средства предпринимателя", "Дивиденды"),
]


def seed(apps, schema_editor):
    Mapping = apps.get_model("reports", "CashflowArticleMapping")
    for article, line in SEED:
        Mapping.objects.get_or_create(article=article, defaults={"report_line": line})


def unseed(apps, schema_editor):
    Mapping = apps.get_model("reports", "CashflowArticleMapping")
    Mapping.objects.filter(article__in=[a for a, _ in SEED]).delete()


class Migration(migrations.Migration):
    dependencies = [("reports", "0004_cashflowarticlemapping")]
    operations = [migrations.RunPython(seed, unseed)]
