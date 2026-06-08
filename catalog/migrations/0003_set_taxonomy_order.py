from django.db import migrations

# Display order requested for the catalog taxonomy.
# (category name, [subcategory names in display order])
CATEGORY_ORDER = [
    (
        "Автомасла",
        [
            "синтетические масла",
            "полусинтетические масла",
            "минеральные масла",
            "масла для сельскохозяйственной и строительной техники",
            "масла для грузовиков",
            "Масла для мототехники и навесных моторов",
            "трансмиссионные масла",
            "индустриальные масла",
        ],
    ),
    (
        "Автожидкости",
        ["антифриз", "тормозная жидкость", "гидравлическая жидкость для ГУР"],
    ),
    (
        "Автохимия и автокосметика",
        [
            "аэрозольные смазки",
            "герметики",
            "клей, фиксатор, шпаклевка",
            "очистители",
            "присадки",
            "средства по уходу за автомобилем",
        ],
    ),
    (
        "Фильтры",
        [
            "фильтры воздушные",
            "фильтры для АКПП",
            "фильтры салонные",
            "фильтры масляные",
            "фильтры топливные",
        ],
    ),
    ("Щётки стеклоочистителя", []),
    ("Ароматизаторы", []),
]


def set_order(apps, schema_editor):
    Category = apps.get_model("catalog", "Category")
    SubCategory = apps.get_model("catalog", "SubCategory")
    for cat_index, (cat_name, subs) in enumerate(CATEGORY_ORDER, start=1):
        category = Category.objects.filter(name=cat_name).first()
        if not category:
            continue
        category.order = cat_index
        category.save(update_fields=["order"])
        for sub_index, sub_name in enumerate(subs, start=1):
            SubCategory.objects.filter(category=category, name=sub_name).update(
                order=sub_index
            )


def clear_order(apps, schema_editor):
    apps.get_model("catalog", "Category").objects.update(order=0)
    apps.get_model("catalog", "SubCategory").objects.update(order=0)


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0002_alter_brand_options_alter_category_options_and_more"),
    ]

    operations = [migrations.RunPython(set_order, clear_order)]
