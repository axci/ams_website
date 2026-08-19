from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm as DjangoPasswordChangeForm,
)


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


class LoginForm(BootstrapFormMixin, AuthenticationForm):
    pass


class PasswordChangeForm(BootstrapFormMixin, DjangoPasswordChangeForm):
    """Bootstrap-styled password change for the self-service «Сменить пароль» page."""


class RegistrationRequestForm(BootstrapFormMixin, forms.Form):
    """Public «отправьте заявку» form on the registration page — emailed to sales."""

    company_name = forms.CharField(label="Наименование компании", max_length=255)
    inn = forms.CharField(label="ИНН", max_length=12)
    email = forms.EmailField(label="Email")
    # Honeypot: hidden from people, but bots tend to fill it. Humans leave it empty.
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean_inn(self):
        inn = (self.cleaned_data.get("inn") or "").strip()
        if not inn.isdigit() or len(inn) not in (10, 12):
            raise forms.ValidationError("ИНН должен содержать 10 или 12 цифр.")
        return inn
