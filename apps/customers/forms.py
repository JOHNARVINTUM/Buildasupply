from django import forms

from .models import CustomerAddress


class CustomerAddressForm(forms.ModelForm):
    class Meta:
        model = CustomerAddress
        fields = [
            "recipient_name", "phone", "address_line1", "address_line2", "barangay",
            "city", "province", "postal_code", "country", "is_default",
        ]
        widgets = {
            "address_line1": forms.TextInput(attrs={"autocomplete": "address-line1"}),
            "address_line2": forms.TextInput(attrs={"autocomplete": "address-line2"}),
            "city": forms.TextInput(attrs={"autocomplete": "address-level2"}),
            "province": forms.TextInput(attrs={"autocomplete": "address-level1"}),
            "postal_code": forms.TextInput(attrs={"autocomplete": "postal-code"}),
            "country": forms.TextInput(attrs={"autocomplete": "country", "maxlength": 2}),
            "phone": forms.TextInput(attrs={"autocomplete": "tel"}),
        }

    def clean_country(self):
        return self.cleaned_data["country"].strip().upper()
