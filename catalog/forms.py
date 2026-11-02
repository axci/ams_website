import re

from django import forms
from django.core.validators import validate_email

from warehouses.models import Warehouse

from .models import Brand, PriceType


def parse_email_list(raw):
    """Split a comma/semicolon/space-separated string into validated emails.

    Returns a list (possibly empty); raises ValidationError on a bad address.
    """
    emails = [e.strip() for e in re.split(r"[,;\s]+", raw or "") if e.strip()]
    for email in emails:
        validate_email(email)
    return emails


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
        emails = parse_email_list(self.cleaned_data["recipients"])
        if not emails:
            raise forms.ValidationError("Укажите хотя бы один адрес.")
        return emails


class ProfilePriceListForm(PriceListEmailForm):
    """The «Отправить прайс» block on the profile page — same as the admin form
    plus a price-type picker, and styled with Bootstrap classes."""

    price_type = forms.ModelChoiceField(
        queryset=PriceType.objects.order_by("order", "name"),
        label="Тип цены",
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )
    # Separate recipients for the «с ТН ВЭД» format, with its own default.
    recipients_tnved = forms.CharField(
        label="Email получателей (с ТН ВЭД)",
        required=False,
    )
    field_order = [
        "price_type", "warehouse", "in_stock_only",
        "recipients", "recipients_tnved",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Both recipient boxes are optional on the form; the view requires the
        # one matching the pressed button (обычный прайс / с ТН ВЭД).
        self.fields["recipients"].required = False
        self.fields["warehouse"].widget.attrs["class"] = "form-select form-select-sm"
        for name in ("recipients", "recipients_tnved"):
            self.fields[name].widget.attrs = {
                "class": "form-control form-control-sm",
                "placeholder": "адрес@почта.ру, ещё@почта.ру",
            }
        self.fields["in_stock_only"].widget.attrs["class"] = "form-check-input"

    def clean_recipients(self):
        return parse_email_list(self.cleaned_data.get("recipients"))

    def clean_recipients_tnved(self):
        return parse_email_list(self.cleaned_data.get("recipients_tnved"))


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
