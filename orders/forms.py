from django import forms

from accounts.forms import BootstrapFormMixin

from .models import Order


class CheckoutForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Order
        fields = ("shipping_address", "comment")
        labels = {
            "shipping_address": "Адрес доставки",
            "comment": "Примечание к заказу",
        }
        widgets = {
            "shipping_address": forms.TextInput(
                attrs={"placeholder": "Город, улица, дом"}
            ),
            "comment": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Необязательно"}
            ),
        }
