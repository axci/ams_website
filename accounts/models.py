from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Site user. Buyers are non-staff users granted access to warehouses."""

    class Type(models.TextChoices):
        LEGAL = "legal", "Юридическое лицо"
        INDIVIDUAL = "individual", "Физическое лицо"

    code = models.CharField("код", max_length=32, unique=True, blank=True, null=True)
    type = models.CharField(
        "тип", max_length=16, choices=Type.choices, default=Type.LEGAL, blank=True
    )
    inn = models.CharField("ИНН", max_length=12, blank=True, default="")
    address = models.CharField("адрес", max_length=255, blank=True, default="")
    debt = models.DecimalField(
        "задолженность", max_digits=12, decimal_places=2, default=0,
        help_text="Заполняется выгрузкой/синхронизацией с ERP.",
    )
    company_name = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    warehouses = models.ManyToManyField(
        "warehouses.Warehouse",
        related_name="buyers",
        blank=True,
        help_text="Warehouses whose stock this buyer is allowed to see.",
    )

    def save(self, *args, **kwargs):
        # Store an empty code as NULL so multiple blank codes don't collide on
        # the unique constraint.
        if not self.code:
            self.code = None
        super().save(*args, **kwargs)

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
