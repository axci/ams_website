from django.db import migrations

SPECS = [
    ("Год основания", "2005", "надёжный партнёр на рынке"),
    ("Регион", "СФО", "Сибирский федеральный округ"),
    ("Направление", "Масла", "смазочные материалы и автохимия"),
]

TAGS = [
    ("Газпромнефть", False),
    ("Лукойл", False),
    ("Татнефть", False),
    ("Тендеры и госзакупки", False),
]

BRANDS = [
    {
        "role": "Официальный дистрибьютор",
        "heading": "SCT — Германия",
        "description": (
            "Официальный дистрибьютор и региональный представитель в Сибирском "
            "федеральном округе продукции завода-производителя SCT: автомобильные "
            "и индустриальные масла, смазки, автохимия, фильтры, запасные части и "
            "охлаждающие жидкости."
        ),
        "chips": [
            ("Mannol", "масла · автохимия"),
            ("SCT", "масла · фильтры"),
            ("Pemco", "масла"),
            ("Chempioil", "масла · смазки"),
            ("Favorit", "автохимия"),
            ("Fanfaro", "масла · смазки"),
        ],
    },
    {
        "role": "Официальный дилер",
        "heading": "Масла, ароматизаторы, аксессуары",
        "description": (
            "Дилер по продажам моторных масел Molygreen, автомобильных "
            "ароматизаторов и автоаксессуаров отечественных и импортных брендов: "
            "пластиковых и алюминиевых канистр, воронок для топлива, "
            "буксировочных тросов, рабочих перчаток и многого другого."
        ),
        "chips": [
            ("Molygreen", "моторные масла"),
            ("Areon", "ароматизаторы"),
            ("Car-Freshner", "ароматизаторы"),
            ("Dr. Marcus", "ароматизаторы"),
            ("Svejo", "ароматизаторы"),
            ("Ladoni", "рабочие перчатки"),
        ],
    },
]

CENTERS = ["Новосибирск", "Кемерово", "Новокузнецк"]

REGIONS = [
    "Новосибирская область",
    "Кемеровская область",
    "Алтайский край",
    "Республика Алтай",
    "Томская область",
]


def seed(apps, schema_editor):
    AboutPage = apps.get_model("about", "AboutPage")
    AboutSpec = apps.get_model("about", "AboutSpec")
    ClientTag = apps.get_model("about", "ClientTag")
    AboutBrandBlock = apps.get_model("about", "AboutBrandBlock")
    AboutBrandChip = apps.get_model("about", "AboutBrandChip")
    SupplyCenter = apps.get_model("about", "SupplyCenter")
    SupplyRegion = apps.get_model("about", "SupplyRegion")

    # Ensure the singletons exist (fields carry the mockup text as defaults).
    page, _ = AboutPage.objects.get_or_create(pk=1)
    apps.get_model("about", "CompanyDetails").objects.get_or_create(pk=1)

    if not AboutSpec.objects.exists():
        for i, (label, value, subtitle) in enumerate(SPECS):
            AboutSpec.objects.create(
                page=page, label=label, value=value, subtitle=subtitle, order=i
            )
    if not ClientTag.objects.exists():
        for i, (text, accent) in enumerate(TAGS):
            ClientTag.objects.create(page=page, text=text, accent=accent, order=i)
    if not AboutBrandBlock.objects.exists():
        for i, b in enumerate(BRANDS):
            block = AboutBrandBlock.objects.create(
                role=b["role"], heading=b["heading"],
                description=b["description"], order=i,
            )
            for j, (name, subtitle) in enumerate(b["chips"]):
                AboutBrandChip.objects.create(
                    block=block, name=name, subtitle=subtitle, order=j
                )
    if not SupplyCenter.objects.exists():
        for i, name in enumerate(CENTERS):
            SupplyCenter.objects.create(page=page, name=name, order=i)
    if not SupplyRegion.objects.exists():
        for i, name in enumerate(REGIONS):
            SupplyRegion.objects.create(page=page, name=name, order=i)


def unseed(apps, schema_editor):
    for model in ("AboutSpec", "ClientTag", "AboutBrandChip",
                  "AboutBrandBlock", "SupplyCenter", "SupplyRegion"):
        apps.get_model("about", model).objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("about", "0006_aboutbrandblock_aboutpage_companydetails_card_pdf_and_more"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
