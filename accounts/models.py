from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Site user. Buyers are non-staff users granted access to warehouses."""

    company_name = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    warehouses = models.ManyToManyField(
        "warehouses.Warehouse",
        related_name="buyers",
        blank=True,
        help_text="Warehouses whose stock this buyer is allowed to see.",
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
