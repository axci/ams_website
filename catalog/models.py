from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils.text import slugify


class Brand(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    logo = models.ImageField(upload_to="brands/", blank=True, null=True)
    order = models.PositiveIntegerField(
        default=0, help_text="Display order on the site (lower numbers first)."
    )
    categories = models.ManyToManyField(
        "Category",
        related_name="brands",
        blank=True,
        help_text="Категории, доступные для этого бренда (пусто = все категории).",
    )
    hidden_warehouses = models.ManyToManyField(
        "warehouses.Warehouse",
        related_name="hidden_brands",
        blank=True,
        help_text="Склады, на которых бренд скрыт (пусто = виден везде).",
    )

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Category(models.Model):
    name = models.CharField(max_length=150, unique=True)
    order = models.PositiveIntegerField(
        default=0, help_text="Display order on the site (lower numbers first)."
    )

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "category"
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class SubCategory(models.Model):
    category = models.ForeignKey(
        Category, on_delete=models.CASCADE, related_name="subcategories"
    )
    name = models.CharField(max_length=150)
    order = models.PositiveIntegerField(
        default=0,
        help_text="Display order within the category (lower numbers first).",
    )

    class Meta:
        ordering = ["category", "order", "name"]
        verbose_name = "subcategory"
        verbose_name_plural = "subcategories"
        constraints = [
            models.UniqueConstraint(
                fields=["category", "name"],
                name="unique_subcategory_per_category",
            )
        ]

    def __str__(self):
        return f"{self.category.name} / {self.name}"


class ModelProduct(models.Model):
    """A product model / line a product may belong to (optional).

    Scoped to a brand: the same model name may exist under different brands
    (identified by id), so «Selection» for one brand is a distinct model from
    «Selection» for another.
    """

    name = models.CharField(max_length=200)
    brand = models.ForeignKey(
        "Brand",
        on_delete=models.CASCADE,
        related_name="product_models",
        null=True,
        blank=True,
        verbose_name="бренд",
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "product model"
        verbose_name_plural = "product models"
        constraints = [
            models.UniqueConstraint(
                fields=["brand", "name"], name="unique_brand_model_name"
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.brand})" if self.brand_id else self.name


class Product(models.Model):
    # Unique identifier for the product.
    sku = models.CharField("Код 1С", max_length=64, unique=True, db_index=True)
    # Additional, non-unique references.
    article = models.CharField("артикул", max_length=64, blank=True, db_index=True)
    manufacturer_number = models.CharField("Номер производителя", max_length=64, blank=True, db_index=True)

    name = models.CharField("наименование", max_length=200)
    slug = models.SlugField(max_length=220, blank=True, allow_unicode=True)
    brand = models.ForeignKey(
        Brand, on_delete=models.PROTECT, related_name="products"
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        related_name="products",
        blank=True,
        null=True,
    )
    subcategory = models.ForeignKey(
        SubCategory,
        on_delete=models.SET_NULL,
        related_name="products",
        blank=True,
        null=True,
    )
    model_product = models.ForeignKey(
        ModelProduct,
        on_delete=models.SET_NULL,
        related_name="products",
        blank=True,
        null=True,
    )
    weight = models.DecimalField(
        "вес",
        max_digits=10,
        decimal_places=3,
        blank=True,
        null=True,
        help_text="Вес в указанной единице измерения",
    )
    weight_unit = models.CharField(
        "единица измерения веса", max_length=16, default="кг", blank=True
    )
    volume = models.DecimalField(
        "объём",
        max_digits=10,
        decimal_places=3,
        blank=True,
        null=True,
        help_text="Объём в указанной единице измерения",
    )
    volume_unit = models.CharField(
        "единица измерения объёма", max_length=16, default="л", blank=True
    )
    pack_quantity = models.PositiveIntegerField(
        "количество штук в упаковке",
        blank=True,
        null=True,
        help_text="Сколько штук товара в одной упаковке.",
    )
    viscosity = models.CharField(
        "вязкость",
        max_length=20,
        blank=True,
        db_index=True,
        help_text="Например: 5W30, 0W20 (только для подходящих товаров).",
    )
    picture = models.ImageField("изображение", upload_to="products/", blank=True, null=True)
    picture_thumb = models.ImageField(
        upload_to="products/thumbs/", blank=True, null=True, editable=False
    )
    description = models.TextField("описание", blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vat_rate = models.DecimalField(
        "ставка НДС, %", max_digits=5, decimal_places=2, default=22
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "товар"
        verbose_name_plural = "товары"

    def __str__(self):
        return f"{self.sku} — {self.name}"

    def clean(self):
        # Keep subcategory consistent with the chosen category.
        if (
            self.subcategory_id
            and self.category_id
            and self.subcategory.category_id != self.category_id
        ):
            raise ValidationError(
                {"subcategory": "Subcategory does not belong to the selected category."}
            )

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name, allow_unicode=True)[:220]
        if self.picture and (not self.picture_thumb or self._picture_changed()):
            self.generate_thumbnail()
        super().save(*args, **kwargs)

    def _picture_changed(self):
        if not self.pk:
            return True
        old = (
            type(self).objects.filter(pk=self.pk)
            .values_list("picture", flat=True)
            .first()
        )
        return old != self.picture.name

    def generate_thumbnail(self):
        """Build a small JPEG thumbnail of `picture` into `picture_thumb`."""
        from io import BytesIO

        from django.core.files.base import ContentFile
        from PIL import Image

        # Read the original bytes once, then rewind (do NOT close) the picture:
        # on an admin upload the same file object is read again by the storage
        # backend during the following save(), so closing it here would raise
        # "I/O operation on closed file".
        try:
            self.picture.open("rb")
            raw = self.picture.read()
        except Exception:
            return
        finally:
            try:
                self.picture.seek(0)
            except (ValueError, OSError):
                pass

        try:
            with Image.open(BytesIO(raw)) as img:
                if img.mode in ("RGBA", "LA", "P"):
                    img = img.convert("RGBA")
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[-1])
                    img = background
                else:
                    img = img.convert("RGB")
                img.thumbnail((400, 400))
                buf = BytesIO()
                img.save(buf, format="JPEG", quality=82, optimize=True)
        except Exception:
            return
        stem = self.picture.name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        self.picture_thumb.save(f"{stem}.jpg", ContentFile(buf.getvalue()), save=False)

    def get_absolute_url(self):
        return reverse("catalog:product_detail", args=[self.pk])

    def price_for(self, price_type):
        """Effective price for the given price type, falling back to `price`."""
        if price_type is not None:
            pp = self.prices.filter(price_type=price_type).first()
            if pp is not None:
                return pp.price
        return self.price


class PriceType(models.Model):
    """A price tier such as «Розничные» or «Крупный ОПТ»."""

    name = models.CharField("название", max_length=100, unique=True)
    order = models.PositiveIntegerField("порядок", default=0)
    is_public = models.BooleanField(
        "цена для гостей",
        default=False,
        help_text="Показывается неавторизованным посетителям.",
    )
    is_default = models.BooleanField(
        "по умолчанию для покупателей",
        default=False,
        help_text="Используется, если у покупателя не задан тип цены.",
    )

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "тип цены"
        verbose_name_plural = "типы цен"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Keep the "public" and "default" flags single-valued.
        if self.is_public:
            PriceType.objects.exclude(pk=self.pk).filter(is_public=True).update(
                is_public=False
            )
        if self.is_default:
            PriceType.objects.exclude(pk=self.pk).filter(is_default=True).update(
                is_default=False
            )

    @classmethod
    def public_type(cls):
        """Price type shown to guests (or the first one as a fallback)."""
        return cls.objects.filter(is_public=True).first() or cls.objects.first()

    @classmethod
    def default_type(cls):
        """Price type for buyers without an explicit one."""
        return cls.objects.filter(is_default=True).first() or cls.public_type()


class ProductPrice(models.Model):
    """Price of a product for a particular price type."""

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="prices"
    )
    price_type = models.ForeignKey(PriceType, on_delete=models.CASCADE, related_name="+")
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["product", "price_type"], name="unique_product_price_type"
            )
        ]
        ordering = ["price_type__order"]
        verbose_name = "цена"
        verbose_name_plural = "цены"

    def __str__(self):
        return f"{self.product.sku} — {self.price_type}: {self.price}"


class BannerSlide(models.Model):
    """A full-width banner image shown on the main page (uploaded in the admin)."""

    image = models.ImageField(upload_to="banners/")
    caption = models.CharField(max_length=200, blank=True)
    link_url = models.URLField("link URL", blank=True, help_text="Optional click-through link.")
    order = models.PositiveIntegerField(default=0, help_text="Lower numbers show first.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "banner slide"
        verbose_name_plural = "banner slides"

    def __str__(self):
        return self.caption or f"Slide #{self.pk}"
