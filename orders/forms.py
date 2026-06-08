from django import forms

from accounts.forms import BootstrapFormMixin

from .models import Order


class CheckoutForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Order
        fields = ("shipping_address", "comment")
        widgets = {
            "shipping_address": forms.TextInput(
                attrs={"placeholder": "Delivery address"}
            ),
            "comment": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Optional note for this order"}
            ),
        }
