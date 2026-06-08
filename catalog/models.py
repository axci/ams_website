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
    """A product model / line a product may belong to (optional)."""

    name = models.CharField(max_length=200, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "product model"
        verbose_name_plural = "product models"

    def __str__(self):
        return self.name


class Product(models.Model):
    # Unique identifier for the product.
    sku = models.CharField("SKU", max_length=64, unique=True, db_index=True)
    # Additional, non-unique references.
    article = models.CharField(max_length=64, db_index=True)
    manufacturer_number = models.CharField(max_length=64, blank=True, db_index=True)

    name = models.CharField(max_length=200)
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
        max_digits=10,
        decimal_places=3,
        blank=True,
        null=True,
        help_text="Weight in kg.",
    )
    volume = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        blank=True,
        null=True,
        help_text="Volume in litres.",
    )
    picture = models.ImageField(upload_to="products/", blank=True, null=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

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
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("catalog:product_detail", args=[self.pk])


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
