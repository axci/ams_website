import re

from django import forms
from django.core.validators import validate_email

from warehouses.models import Warehouse

from .models import Brand, PriceType


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


class ProfilePriceListForm(PriceListEmailForm):
    """The «Отправить прайс» block on the profile page — same as the admin form
    plus a price-type picker, and styled with Bootstrap classes."""

    price_type = forms.ModelChoiceField(
        queryset=PriceType.objects.order_by("order", "name"),
        label="Тип цены",
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )
    field_order = ["price_type", "warehouse", "recipients", "in_stock_only"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["warehouse"].widget.attrs["class"] = "form-select form-select-sm"
        self.fields["recipients"].widget.attrs = {
            "class": "form-control form-control-sm",
            "placeholder": "адрес@почта.ру, ещё@почта.ру",
        }
        self.fields["in_stock_only"].widget.attrs["class"] = "form-check-input"


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
