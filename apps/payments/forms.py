from django import forms


class DemoPaymentForm(forms.Form):
    method_category = forms.ChoiceField(
        choices=[("EWALLET", "Demo e-wallet")],
        label="Payment method",
    )
    idempotency_key = forms.CharField(max_length=128, widget=forms.HiddenInput)
