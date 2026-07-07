from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import User


class BootstrapFormMixin:
    """Add Bootstrap CSS classes to every field widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-check-input")
            else:
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} form-control".strip()


class RegisterForm(BootstrapFormMixin, UserCreationForm):
    email = forms.EmailField(required=True, label="Эл. почта")
    company_name = forms.CharField(required=False, max_length=200, label="Компания")
    phone = forms.CharField(required=False, max_length=40, label="Телефон")

    class Meta:
        model = User
        fields = ("username", "email")

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            name = self.cleaned_data.get("company_name") or ""
            phone = self.cleaned_data.get("phone") or ""
            if name or phone:
                from .models import Company

                Company.objects.create(user=user, company_name=name, phone=phone)
        return user


class LoginForm(BootstrapFormMixin, AuthenticationForm):
    pass
