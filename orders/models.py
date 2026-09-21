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

    class PaymentMethod(models.TextChoices):
        CASH = "cash", "Наличные"
        CASHLESS = "cashless", "Безналичные"

    class DeliveryMethod(models.TextChoices):
        DELIVERY = "delivery", "Доставка"
        PICKUP = "pickup", "Самовывоз"

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
    payment_method = models.CharField(
        "способ оплаты",
        max_length=20,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASHLESS,
    )
    delivery_method = models.CharField(
        "способ получения",
        max_length=20,
        choices=DeliveryMethod.choices,
        default=DeliveryMethod.DELIVERY,
    )
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

    @property
    def is_pickup(self):
        """Buyer collects the order at the warehouse instead of delivery."""
        return self.delivery_method == self.DeliveryMethod.PICKUP

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


class SalesRecord(models.Model):
    """A sale line imported from the 1C «Ведомость по товарам» export
    (Расходная накладная / Корректировка реализации). Distinct from the site's
    own Order — this is external sales statistics, visible to authorised users."""

    date = models.DateTimeField("дата документа", blank=True, null=True)
    warehouse = models.ForeignKey(
        "warehouses.Warehouse",
        on_delete=models.PROTECT,
        related_name="sales_records",
        verbose_name="склад",
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.SET_NULL,
        related_name="sales_records",
        blank=True,
        null=True,
        verbose_name="товар",
        help_text="Сопоставляется по Коду 1С; пусто — если товара нет в каталоге.",
    )
    sku = models.CharField("Код 1С", max_length=64, db_index=True)
    client = models.CharField("контрагент", max_length=255, blank=True)
    client_type = models.CharField("тип контрагента", max_length=120, blank=True)
    quantity = models.DecimalField("расход", max_digits=12, decimal_places=3, default=0)
    document = models.CharField("документ", max_length=255)
    document_type = models.CharField("тип документа", max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "продажа"
        verbose_name_plural = "статистика продаж"
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(
                fields=["warehouse", "sku", "document"], name="unique_sale_line"
            )
        ]
        indexes = [models.Index(fields=["-date"])]

    def __str__(self):
        return f"{self.sku} · {self.warehouse_id} · {self.document}"


class StockSnapshot(models.Model):
    """Day-by-day product stock at a warehouse, reconstructed from the 1C
    «Ведомость по товарам» running balances (нач./кон. остаток). One row is the
    stock at the END of that date; the beginning of a date equals the previous
    day's value."""

    sku = models.CharField("Код 1С", max_length=64, db_index=True)
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.SET_NULL,
        related_name="stock_snapshots",
        blank=True,
        null=True,
        verbose_name="товар",
    )
    warehouse = models.ForeignKey(
        "warehouses.Warehouse",
        on_delete=models.PROTECT,
        related_name="stock_snapshots",
        verbose_name="склад",
    )
    date = models.DateField("дата", db_index=True)
    quantity = models.DecimalField(
        "остаток на конец дня", max_digits=12, decimal_places=3, default=0
    )

    class Meta:
        verbose_name = "остаток (история)"
        verbose_name_plural = "история остатков"
        ordering = ["sku", "warehouse", "date"]
        constraints = [
            models.UniqueConstraint(
                fields=["sku", "warehouse", "date"], name="unique_stock_snapshot"
            )
        ]
        indexes = [models.Index(fields=["warehouse", "date"])]

    def __str__(self):
        return f"{self.sku} @ {self.warehouse_id} {self.date}: {self.quantity}"


class PurchaseOrder(models.Model):
    """A replenishment order to a supplier, built from sales velocity and
    current stock. Warehouses are pooled (treated as one)."""

    supplier = models.CharField("поставщик", max_length=255)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="purchase_orders",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Parameters the suggestion was built with (kept for the record).
    delivery_days = models.PositiveIntegerField("срок поставки, дней", default=0)
    safety_days = models.PositiveIntegerField("страховой запас, дней", default=0)
    sales_period_days = models.PositiveIntegerField("период продаж, дней", default=90)
    note = models.TextField("примечание", blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "заказ поставщику"
        verbose_name_plural = "заказы поставщикам"

    def __str__(self):
        return f"Заказ №{self.pk} — {self.supplier}"

    @property
    def total_qty(self):
        return sum(i.quantity for i in self.items.all())

    @property
    def positions(self):
        return self.items.count()


class PurchaseOrderItem(models.Model):
    order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.SET_NULL, null=True, related_name="+"
    )
    # Snapshots so the order stands on its own even if the product changes.
    sku = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField("заказать", default=0)
    current_stock = models.IntegerField("остаток на момент заказа", default=0)
    avg_daily_sales = models.DecimalField(
        "продаж в день", max_digits=12, decimal_places=3, default=0
    )
    suggested_qty = models.PositiveIntegerField("рекомендовано", default=0)

    class Meta:
        ordering = ["-quantity", "name"]

    def __str__(self):
        return f"{self.sku} × {self.quantity}"
