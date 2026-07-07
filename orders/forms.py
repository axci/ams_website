from django import forms
from django.core.exceptions import ValidationError

from accounts.forms import BootstrapFormMixin
from accounts.models import Company, DeliveryAddress


class CheckoutForm(BootstrapFormMixin, forms.Form):
    company = forms.ModelChoiceField(
        queryset=Company.objects.none(),
        label="Компания",
        empty_label=None,
    )
    delivery_address = forms.ModelChoiceField(
        queryset=DeliveryAddress.objects.none(),
        label="Адрес доставки",
        required=False,
        empty_label="— выбрать сохранённый —",
    )
    new_delivery_address = forms.CharField(
        label="или новый адрес",
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={"placeholder": "Город, улица, дом"}),
    )
    comment = forms.CharField(
        label="Примечание к заказу",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Необязательно"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["company"].queryset = user.companies.all()
            self.fields["delivery_address"].queryset = user.delivery_addresses.all()

    def clean(self):
        cleaned = super().clean()
        addr = cleaned.get("delivery_address")
        new_addr = (cleaned.get("new_delivery_address") or "").strip()
        if not addr and not new_addr:
            raise ValidationError(
                "Укажите адрес доставки — выберите сохранённый или введите новый."
            )
        return cleaned
