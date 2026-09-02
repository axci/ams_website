from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Site user. Buyers are non-staff users granted access to warehouses.

    Buyer requisites (Код, ИНН, задолженность, …) live on related `Company`
    records — a user may have several.
    """

    manager = models.ForeignKey(
        "warehouses.Manager",
        on_delete=models.SET_NULL,
        related_name="clients",
        blank=True,
        null=True,
        verbose_name="менеджер",
        help_text="Персональный менеджер покупателя.",
    )
    manager_profile = models.OneToOneField(
        "warehouses.Manager",
        on_delete=models.SET_NULL,
        related_name="account",
        blank=True,
        null=True,
        verbose_name="профиль менеджера",
        help_text="Если задано, пользователь входит как этот менеджер и видит "
        "в «Кабинете менеджера» своих клиентов.",
    )
    price_type = models.ForeignKey(
        "catalog.PriceType",
        on_delete=models.SET_NULL,
        related_name="users",
        blank=True,
        null=True,
        verbose_name="тип цены",
        help_text="Пусто = тип по умолчанию (Крупный ОПТ).",
    )
    show_stock = models.BooleanField(
        "показывать точный остаток",
        default=False,
        help_text="Если выключено, покупатель видит «много / мало / только N» "
        "вместо точного количества.",
    )
    free_delivery_min = models.DecimalField(
        "мин. сумма для доставки",
        max_digits=12,
        decimal_places=2,
        default=3000,
        help_text="Заказ с доставкой ниже этой суммы оформить нельзя "
        "(самовывоз — без ограничения).",
    )
    warehouses = models.ManyToManyField(
        "warehouses.Warehouse",
        related_name="buyers",
        blank=True,
        help_text=(
            "Склады, с которых покупатель заказывает сразу («его» склады). "
            "Остаток на других складах доступен с пометкой «Доставка 7 дней»."
        ),
    )

    def __str__(self):
        return self.get_full_name() or self.username

    def accessible_warehouses(self):
        """Active warehouses this user may view stock for.

        Staff/superusers can see every active warehouse; buyers see only the
        ones explicitly assigned to them.
        """
        from warehouses.models import Warehouse

        if self.is_staff or self.is_superuser:
            return Warehouse.objects.filter(is_active=True)
        return self.warehouses.filter(is_active=True)

    def total_debt(self):
        """Combined debt across all of the user's companies."""
        return sum((c.debt for c in self.companies.all()), Decimal("0"))


class Company(models.Model):
    """A buyer's company / counterparty (Контрагент). One login (User) may have
    several; imported companies may not be linked to a login yet."""

    class Type(models.TextChoices):
        LEGAL = "legal", "Юридическое лицо"
        INDIVIDUAL = "individual", "Физическое лицо"

    users = models.ManyToManyField(
        User,
        related_name="companies",
        blank=True,
        verbose_name="аккаунты",
        help_text="Личные кабинеты, которым принадлежит компания "
        "(одну компанию можно назначить нескольким пользователям).",
    )
    code = models.CharField("код", max_length=32, unique=True, blank=True, null=True)
    type = models.CharField(
        "тип", max_length=16, choices=Type.choices, default=Type.LEGAL, blank=True
    )
    inn = models.CharField("ИНН", max_length=12, blank=True, default="")
    kpp = models.CharField("КПП", max_length=9, blank=True, default="")
    address = models.CharField("адрес", max_length=255, blank=True, default="")
    debt = models.DecimalField(
        "задолженность", max_digits=12, decimal_places=2, default=0,
        help_text="Заполняется выгрузкой/синхронизацией с ERP.",
    )
    company_name = models.CharField("название", max_length=200, blank=True)
    phone = models.CharField("телефон", max_length=40, blank=True)

    class Meta:
        verbose_name = "компания"
        verbose_name_plural = "компании"
        ordering = ["company_name", "code"]

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = None
        super().save(*args, **kwargs)

    def __str__(self):
        return self.company_name or self.code or f"Компания #{self.pk}"


class RegistrationRequest(models.Model):
    """A «заявка на регистрацию» submitted from the public register page.

    Stored so the sales team can process it in the admin: from a request they
    create the buyer's account and email the login/password with one button.
    """

    class Status(models.TextChoices):
        NEW = "new", "Новая"
        PROCESSED = "processed", "Обработана"
        REJECTED = "rejected", "Отклонена"

    company_name = models.CharField("наименование компании", max_length=255)
    inn = models.CharField("ИНН", max_length=12, blank=True, default="")
    email = models.EmailField("email")
    status = models.CharField(
        "статус", max_length=16, choices=Status.choices, default=Status.NEW
    )
    note = models.TextField("примечание", blank=True)
    created_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="+",
        blank=True,
        null=True,
        verbose_name="созданный аккаунт",
        help_text="Аккаунт, созданный по этой заявке.",
    )
    created_at = models.DateTimeField("получена", auto_now_add=True)
    processed_at = models.DateTimeField("обработана", blank=True, null=True)

    class Meta:
        verbose_name = "заявка на регистрацию"
        verbose_name_plural = "заявки на регистрацию"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.company_name} ({self.email})"


class DeliveryAddress(models.Model):
    """A saved delivery address a buyer can pick at checkout."""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="delivery_addresses"
    )
    label = models.CharField("название", max_length=100, blank=True)
    address = models.CharField("адрес", max_length=255)

    class Meta:
        verbose_name = "адрес доставки"
        verbose_name_plural = "адреса доставки"
        ordering = ["label", "address"]

    def __str__(self):
        return f"{self.label}: {self.address}" if self.label else self.address
