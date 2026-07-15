from django.conf import settings
from django.db import models


class Cart(models.Model):
    """A persistent basket; one per user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cart"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cart of {self.user}"

    @property
    def items_count(self):
        return sum(item.quantity for item in self.items.all())

    @property
    def total(self):
        return sum((item.subtotal for item in self.items.all()), start=0)


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cart", "product"], name="unique_cart_product"
            )
        ]
        ordering = ["added_at"]

    def __str__(self):
        return f"{self.quantity} × {self.product.sku}"

    @property
    def unit_price(self):
        """Unit price for the cart owner's price type."""
        from catalog.pricing import price_type_for_user

        return self.product.price_for(price_type_for_user(self.cart.user))

    @property
    def subtotal(self):
        return self.unit_price * self.quantity


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает"
        CONFIRMED = "confirmed", "Подтверждён"
        SHIPPED = "shipped", "Отправлен"
        DELIVERED = "delivered", "Доставлен"
        CANCELLED = "cancelled", "Отменён"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders"
    )
    warehouse = models.ForeignKey(
        "warehouses.Warehouse", on_delete=models.PROTECT, related_name="orders"
    )
    company = models.ForeignKey(
        "accounts.Company",
        on_delete=models.PROTECT,
        related_name="orders",
        blank=True,
        null=True,
        verbose_name="компания",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_address = models.CharField(max_length=255, blank=True)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Order #{self.pk} ({self.get_status_display()})"

    @property
    def invoice_number(self):
        return f"W{self.pk}"

    @property
    def is_cancellable(self):
        """A buyer may cancel only while the order is still pending."""
        return self.status == self.Status.PENDING

    def recalculate_total(self, save=True):
        self.total = sum((item.subtotal for item in self.items.all()), start=0)
        if save:
            self.save(update_fields=["total"])
        return self.total


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.PROTECT, related_name="order_items"
    )
    # Snapshots so the order is unaffected by later catalog changes.
    sku = models.CharField(max_length=64)
    name = models.CharField(max_length=200)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.quantity} × {self.sku} (order #{self.order_id})"

    @property
    def subtotal(self):
        if self.price is None or self.quantity is None:
            return None
        return self.price * self.quantity


class Favorite(models.Model):
    """A product saved to a user's wishlist (Избранное)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favorites"
    )
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.CASCADE, related_name="favorited_by"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "product"], name="unique_user_favorite"
            )
        ]

    def __str__(self):
        return f"{self.user} ♥ {self.product_id}"
