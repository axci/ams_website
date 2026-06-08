"""Populate the database with demo data so the site is usable immediately.

Run with:  python manage.py seed_demo
It is safe to run more than once (existing records are reused; existing field
values are never overwritten).
"""

import random
from io import BytesIO

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from catalog.models import Brand, Category, ModelProduct, Product, SubCategory
from warehouses.models import Stock, Warehouse

try:
    from PIL import Image, ImageDraw, ImageFont

    HAS_PIL = True
except ImportError:  # pragma: no cover
    HAS_PIL = False

WAREHOUSES = [
    ("Berlin Central", "WH-BER", "Alexanderplatz 1, Berlin"),
    ("Warsaw Depot", "WH-WAW", "Marszałkowska 10, Warsaw"),
    ("Amsterdam Hub", "WH-AMS", "Damrak 5, Amsterdam"),
]

BRANDS = ["Mobil", "Castrol", "Shell", "Liqui Moly", "Bosch", "Mann-Filter"]

# Category -> list of subcategories (empty list = no subcategories).
# Order in this dict / lists is the display order.
TAXONOMY = {
    "Автомасла": [
        "синтетические масла",
        "полусинтетические масла",
        "минеральные масла",
        "масла для сельскохозяйственной и строительной техники",
        "масла для грузовиков",
        "Масла для мототехники и навесных моторов",
        "трансмиссионные масла",
        "индустриальные масла",
    ],
    "Автожидкости": [
        "антифриз",
        "тормозная жидкость",
        "гидравлическая жидкость для ГУР",
    ],
    "Автохимия и автокосметика": [
        "аэрозольные смазки",
        "герметики",
        "клей, фиксатор, шпаклевка",
        "очистители",
        "присадки",
        "средства по уходу за автомобилем",
    ],
    "Фильтры": [
        "фильтры воздушные",
        "фильтры для АКПП",
        "фильтры салонные",
        "фильтры масляные",
        "фильтры топливные",
    ],
    "Щётки стеклоочистителя": [],
    "Ароматизаторы": [],
}

# (sku, article, manufacturer_number, name, brand, category, subcategory, price, description)
PRODUCTS = [
    ("MOB-10001", "152560", "5W30-ESP-1L", "Mobil 1 ESP 5W-30", "Mobil",
     "Автомасла", "синтетические масла", "62.50",
     "Полностью синтетическое моторное масло для современных бензиновых и дизельных двигателей."),
    ("CAS-10002", "15A4B7", "EDGE-5W40", "Castrol EDGE 5W-40", "Castrol",
     "Автомасла", "синтетические масла", "58.90",
     "Синтетическое масло с технологией FLUID TITANIUM для работы под высокой нагрузкой."),
    ("SHL-10003", "550046372", "HX7-10W40", "Shell Helix HX7 10W-40", "Shell",
     "Автомасла", "полусинтетические масла", "34.20",
     "Полусинтетическое моторное масло для надёжной защиты двигателя."),
    ("LM-10004", "2542", "", "Liqui Moly MoS2 15W-40", "Liqui Moly",
     "Автомасла", "минеральные масла", "29.90",
     "Минеральное масло с дисульфидом молибдена для снижения трения."),
    ("MOB-10005", "153688", "DELVAC-15W40", "Mobil Delvac MX 15W-40", "Mobil",
     "Автомасла", "масла для грузовиков", "71.00",
     "Моторное масло для дизельных двигателей грузовых автомобилей."),
    ("CAS-10006", "154F2A", "TRANSMAX-ATF", "Castrol Transmax ATF DEX/MERC", "Castrol",
     "Автомасла", "трансмиссионные масла", "26.40",
     "Трансмиссионная жидкость для автоматических коробок передач."),
    ("LM-10007", "21140", "ANTIFRZ-G12", "Liqui Moly Antifreeze G12+", "Liqui Moly",
     "Автожидкости", "антифриз", "18.75",
     "Концентрат антифриза на основе этиленгликоля, класс G12+."),
    ("BOS-10008", "1987479112", "DOT4", "Bosch Brake Fluid DOT 4", "Bosch",
     "Автожидкости", "тормозная жидкость", "12.30",
     "Тормозная жидкость DOT 4 с высокой температурой кипения."),
    ("LM-10009", "1145", "PSF-HYDRO", "Liqui Moly Power Steering Fluid", "Liqui Moly",
     "Автожидкости", "гидравлическая жидкость для ГУР", "15.60",
     "Гидравлическая жидкость для систем гидроусилителя руля."),
    ("LM-10010", "4084", "", "Liqui Moly Silicone Spray", "Liqui Moly",
     "Автохимия и автокосметика", "аэрозольные смазки", "9.80",
     "Аэрозольная силиконовая смазка для уплотнителей и пластиковых деталей."),
    ("BOS-10011", "0986AF0001", "", "Bosch Air Filter S0001", "Bosch",
     "Фильтры", "фильтры воздушные", "14.90",
     "Воздушный фильтр для легковых автомобилей."),
    ("MAN-10012", "W71280", "W7-12-80", "Mann-Filter Oil Filter W 712/80", "Mann-Filter",
     "Фильтры", "фильтры масляные", "8.40",
     "Масляный фильтр для бензиновых двигателей."),
    ("BOS-10013", "1987432097", "", "Bosch Cabin Filter M2097", "Bosch",
     "Фильтры", "фильтры салонные", "11.20",
     "Салонный фильтр для очистки воздуха в салоне автомобиля."),
    ("BOS-10014", "3397007620", "AEROTWIN-620", "Bosch Aerotwin Wiper 600/400", "Bosch",
     "Щётки стеклоочистителя", "", "21.50",
     "Комплект бескаркасных щёток стеклоочистителя."),
    ("LM-10015", "21283", "", "Aroma Vanilla Air Freshener", "Liqui Moly",
     "Ароматизаторы", "", "3.90",
     "Ароматизатор воздуха для салона автомобиля, аромат ванили."),
]

# sku -> (weight_kg, volume_litres, model_product name).  None = leave blank,
# so several products intentionally have no volume and/or no model.
SPECS = {
    "MOB-10001": ("0.88", "1.0", "Mobil 1"),
    "CAS-10002": ("0.85", "1.0", "Castrol EDGE"),
    "SHL-10003": ("3.40", "4.0", "Shell Helix"),
    "LM-10004": ("4.50", "5.0", "Liqui Moly MoS2"),
    "MOB-10005": ("18.50", "20.0", "Mobil Delvac"),
    "CAS-10006": ("0.90", "1.0", "Castrol Transmax"),
    "LM-10007": ("1.08", "1.0", None),
    "BOS-10008": ("0.55", "0.5", None),
    "LM-10009": ("0.95", "1.0", None),
    "LM-10010": ("0.30", "0.3", None),
    "BOS-10011": ("0.35", None, None),
    "MAN-10012": ("0.20", None, None),
    "BOS-10013": ("0.25", None, None),
    "BOS-10014": ("0.30", None, "Bosch Aerotwin"),
    "LM-10015": ("0.10", "0.05", None),
}

BUYERS = [
    {
        "username": "buyer1",
        "email": "buyer1@example.com",
        "password": "buyerpass123",
        "company_name": "Northwind Trading",
        "warehouses": ["WH-BER", "WH-WAW"],
    },
    {
        "username": "buyer2",
        "email": "buyer2@example.com",
        "password": "buyerpass123",
        "company_name": "Contoso Retail",
        "warehouses": ["WH-AMS"],
    },
]

PALETTE = {
    "Mobil": (13, 71, 161),
    "Castrol": (0, 121, 64),
    "Shell": (211, 47, 47),
    "Liqui Moly": (198, 12, 48),
    "Bosch": (122, 17, 70),
    "Mann-Filter": (191, 87, 0),
}


def _load_font(size):
    for path in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _make_image(name, color):
    """Generate a simple placeholder PNG for a product."""
    img = Image.new("RGB", (600, 600), color)
    draw = ImageDraw.Draw(img)
    font = _load_font(40)

    words, lines, line = name.split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= 520:
            line = trial
        else:
            lines.append(line)
            line = word
    lines.append(line)

    total_h = sum(draw.textbbox((0, 0), ln, font=font)[3] + 10 for ln in lines)
    y = (600 - total_h) / 2
    for ln in lines:
        bbox = draw.textbbox((0, 0), ln, font=font)
        w = bbox[2] - bbox[0]
        draw.text(((600 - w) / 2, y), ln, fill="white", font=font)
        y += (bbox[3] - bbox[1]) + 10

    buf = BytesIO()
    img.save(buf, "PNG")
    return ContentFile(buf.getvalue())


class Command(BaseCommand):
    help = "Seed the database with demo warehouses, products, stock and buyers."

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(42)

        warehouses = {}
        for name, code, address in WAREHOUSES:
            wh, _ = Warehouse.objects.get_or_create(
                code=code, defaults={"name": name, "address": address}
            )
            warehouses[code] = wh
        self.stdout.write(f"Warehouses: {len(warehouses)}")

        brands = {n: Brand.objects.get_or_create(name=n)[0] for n in BRANDS}

        # Categories and their subcategories (TAXONOMY order = display order).
        categories, subcategories = {}, {}
        for cat_index, (cat_name, subs) in enumerate(TAXONOMY.items(), start=1):
            cat, _ = Category.objects.get_or_create(
                name=cat_name, defaults={"order": cat_index}
            )
            if cat.order != cat_index:
                cat.order = cat_index
                cat.save(update_fields=["order"])
            categories[cat_name] = cat
            for sub_index, sub_name in enumerate(subs, start=1):
                sub, _ = SubCategory.objects.get_or_create(
                    category=cat, name=sub_name, defaults={"order": sub_index}
                )
                if sub.order != sub_index:
                    sub.order = sub_index
                    sub.save(update_fields=["order"])
                subcategories[(cat_name, sub_name)] = sub

        # Product models referenced by SPECS.
        model_names = sorted({m for _, _, m in SPECS.values() if m})
        model_products = {
            m: ModelProduct.objects.get_or_create(name=m)[0] for m in model_names
        }
        self.stdout.write(
            f"Brands: {len(brands)}, Categories: {len(categories)}, "
            f"Subcategories: {len(subcategories)}, Product models: {len(model_products)}"
        )

        created_products = 0
        for (
            sku,
            article,
            mfr_number,
            name,
            brand_name,
            cat_name,
            sub_name,
            price,
            desc,
        ) in PRODUCTS:
            subcategory = subcategories.get((cat_name, sub_name)) if sub_name else None
            product, created = Product.objects.get_or_create(
                sku=sku,
                defaults={
                    "article": article,
                    "manufacturer_number": mfr_number,
                    "name": name,
                    "brand": brands[brand_name],
                    "category": categories[cat_name],
                    "subcategory": subcategory,
                    "price": price,
                    "description": desc,
                },
            )
            if created:
                created_products += 1
                if HAS_PIL and not product.picture:
                    product.picture.save(
                        f"{sku}.png",
                        _make_image(name, PALETTE.get(brand_name, (90, 90, 90))),
                        save=True,
                    )

            # Populate spec fields only when empty (never overwrite edits).
            weight, volume, model_name = SPECS.get(sku, (None, None, None))
            to_update = []
            if weight is not None and product.weight is None:
                product.weight = weight
                to_update.append("weight")
            if volume is not None and product.volume is None:
                product.volume = volume
                to_update.append("volume")
            if model_name and product.model_product_id is None:
                product.model_product = model_products[model_name]
                to_update.append("model_product")
            if to_update:
                product.save(update_fields=to_update)

            for code, wh in warehouses.items():
                Stock.objects.get_or_create(
                    product=product,
                    warehouse=wh,
                    defaults={"quantity": random.choice([0, 0, 5, 12, 25, 40, 80])},
                )
        self.stdout.write(
            f"Products: {Product.objects.count()} ({created_products} new), "
            f"Stock rows: {Stock.objects.count()}"
        )

        for data in BUYERS:
            buyer, created = User.objects.get_or_create(
                username=data["username"],
                defaults={
                    "email": data["email"],
                    "company_name": data["company_name"],
                },
            )
            if created:
                buyer.set_password(data["password"])
                buyer.save()
            buyer.warehouses.set([warehouses[c] for c in data["warehouses"]])
        self.stdout.write(f"Buyers: {len(BUYERS)}")

        # Convenience admin for local development only.
        admin, created = User.objects.get_or_create(
            username="admin",
            defaults={
                "email": "admin@example.com",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if created:
            admin.set_password("admin12345")
            admin.save()

        self.stdout.write(self.style.SUCCESS("\nDemo data ready."))
        self.stdout.write("  Admin:  admin / admin12345   (DEV ONLY — change this!)")
        self.stdout.write("  Buyer:  buyer1 / buyerpass123 (Berlin + Warsaw)")
        self.stdout.write("  Buyer:  buyer2 / buyerpass123 (Amsterdam)")
