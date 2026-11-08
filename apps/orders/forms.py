from django import forms

from apps.customers.models import CustomerAddress


class CheckoutSubmissionForm(forms.Form):
    delivery_address = forms.ModelChoiceField(queryset=CustomerAddress.objects.none(), empty_label=None)
    idempotency_key = forms.CharField(max_length=128, widget=forms.HiddenInput)

    def __init__(self, *args, customer, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["delivery_address"].queryset = customer.addresses.order_by("-is_default", "pk")
