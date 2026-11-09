from django import forms

from apps.customers.models import CustomerAddress


class CheckoutSubmissionForm(forms.Form):
    delivery_address = forms.ModelChoiceField(queryset=CustomerAddress.objects.none(), empty_label=None)
    idempotency_key = forms.CharField(max_length=128, widget=forms.HiddenInput)

    def __init__(self, *args, customer, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["delivery_address"].queryset = customer.addresses.order_by("-is_default", "pk")


class DispatchSupplierOrderForm(forms.Form):
    carrier_name = forms.CharField(max_length=120, label="Delivery method or carrier")
    tracking_reference = forms.CharField(max_length=120, label="Tracking or delivery reference")
    notes = forms.CharField(required=False, widget=forms.Textarea, max_length=2000)


class CODCollectionForm(forms.Form):
    amount_minor = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    currency = forms.CharField(max_length=3, widget=forms.HiddenInput)
    collection_reference = forms.CharField(max_length=160, label="Cash collection reference")
    evidence_notes = forms.CharField(required=False, widget=forms.Textarea, max_length=2000, label="Collection evidence or notes")

    def clean_currency(self):
        return self.cleaned_data["currency"].upper()

    def evidence_metadata(self):
        notes = self.cleaned_data.get("evidence_notes", "").strip()
        return {"notes": notes} if notes else {}


class CODExceptionForm(forms.Form):
    status = forms.ChoiceField(choices=(("FAILED_DELIVERY", "Failed delivery"), ("DISPUTED", "Disputed")))
    reason = forms.CharField(max_length=500, widget=forms.Textarea, label="Reason and delivery notes")


class CODCancellationForm(forms.Form):
    reason = forms.CharField(max_length=500, label="Cancellation reason")
