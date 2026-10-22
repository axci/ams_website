import re

from django import forms
from django.core.validators import validate_email

from warehouses.models import Warehouse

from .models import Brand


class PriceListEmailForm(forms.Form):
    """Pick the warehouse (for «свободный остаток»), recipients and scope when
    emailing a price list from the PriceType admin."""

    warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.filter(is_active=True).order_by("name"),
        label="Склад (для свободного остатка)",
    )
    recipients = forms.CharField(
        label="Email получателей",
        help_text="Один или несколько адресов через запятую.",
        widget=forms.TextInput(attrs={"size": 60}),
    )
    in_stock_only = forms.BooleanField(
        required=False, label="Только товары в наличии на складе",
    )

    def clean_recipients(self):
        raw = self.cleaned_data["recipients"]
        emails = [e.strip() for e in re.split(r"[,;\s]+", raw) if e.strip()]
        if not emails:
            raise forms.ValidationError("Укажите хотя бы один адрес.")
        for email in emails:
            validate_email(email)
        return emails


class ProductImportForm(forms.Form):
    file = forms.FileField(label="Excel file (.xlsx)")
    brand = forms.ModelChoiceField(
        queryset=Brand.objects.all(),
        label="Default brand",
        help_text=(
            "Applied to every row that has no 'brand' column "
            "(the sample file has none)."
        ),
    )

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        if not str(uploaded.name).lower().endswith((".xlsx", ".xlsm")):
            raise forms.ValidationError("Please upload an .xlsx file.")
        return uploaded
