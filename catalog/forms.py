from django import forms

from .models import Brand


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
