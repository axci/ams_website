from django.db import models


class Warehouse(models.Model):
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=32, unique=True)
    address = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(
        blank=True, help_text="Orders placed for this warehouse are emailed here."
    )
    picture = models.ImageField(upload_to="warehouses/", blank=True, null=True)
    opening_hours = models.TextField(
        blank=True,
        help_text="Например: Пн–Пт 9:00–18:00, Сб 10:00–15:00, Вс выходной",
    )
    managers = models.ManyToManyField(
        "Manager", related_name="warehouses", blank=True
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class Stock(models.Model):
    """Quantity of a product available in a specific warehouse."""

    product = models.ForeignKey(
        "catalog.Product", on_delete=models.CASCADE, related_name="stocks"
    )
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.CASCADE, related_name="stocks"
    )
    quantity = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["product", "warehouse"], name="unique_product_warehouse"
            )
        ]
        ordering = ["warehouse", "product"]

    def __str__(self):
        return f"{self.product.sku} @ {self.warehouse.code}: {self.quantity}"

    @property
    def in_stock(self):
        return self.quantity > 0


class Manager(models.Model):
    """A warehouse manager / contact person."""

    surname = models.CharField(max_length=120)
    name = models.CharField(max_length=120)
    position = models.CharField("должность", max_length=120, blank=True)
    photo = models.ImageField(upload_to="managers/", blank=True, null=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    order = models.PositiveIntegerField(default=0, help_text="Меньше — выше в списке.")

    class Meta:
        ordering = ["order", "surname", "name"]

    def __str__(self):
        return f"{self.surname} {self.name}".strip()
