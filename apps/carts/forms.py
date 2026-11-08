from django import forms


class CartQuantityForm(forms.Form):
    quantity = forms.IntegerField(min_value=1, label="Quantity")

    def __init__(self, *args, minimum_order_quantity=1, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["quantity"].widget.attrs.update(
            {"min": minimum_order_quantity, "inputmode": "numeric"}
        )
