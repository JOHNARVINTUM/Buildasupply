from decimal import Decimal, InvalidOperation
from django import forms
from .models import Category


class ProductCreateForm(forms.Form):
    name=forms.CharField(max_length=255)
    sku=forms.CharField(label="SKU", max_length=80)
    category=forms.ModelChoiceField(queryset=Category.objects.filter(is_active=True).order_by("display_order", "name"), required=False)
    description=forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}))
    unit_of_measure=forms.CharField(max_length=32, initial="piece")
    minimum_order_quantity=forms.IntegerField(min_value=1, initial=1)
    price_php=forms.DecimalField(label="Price (PHP)", min_value=Decimal("0.01"), max_digits=14, decimal_places=2)
    opening_stock=forms.IntegerField(min_value=0, initial=0)

    def clean_sku(self): return self.cleaned_data["sku"].strip().upper()

    def clean_name(self):
        value=" ".join(self.cleaned_data["name"].split())
        if not value: raise forms.ValidationError("Supply name is required.")
        return value

    def amount_minor(self):
        return int((self.cleaned_data["price_php"] * 100).quantize(Decimal("1")))


class ProductEditForm(ProductCreateForm):
    stock_quantity=forms.IntegerField(min_value=0, label="Available stock")
    opening_stock=None
