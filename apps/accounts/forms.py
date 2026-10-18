from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.validators import RegexValidator
from .models import User
from apps.suppliers.models import Supplier

PH_PHONE = RegexValidator(r"^(?:0?9\d{9}|63?9\d{9}|\+639\d{9}|\+[1-9]\d{7,14})$", "Enter a valid Philippine mobile number or an international E.164 number.")

def normalized_text(value, label):
    value = " ".join(value.strip().split())
    if not value:
        raise forms.ValidationError(f"{label} is required.")
    return value

def normalize_phone(value):
    compact = value.strip().replace(" ", "").replace("-", "")
    PH_PHONE(compact)
    if compact.startswith("09"): return "+63" + compact[1:]
    if compact.startswith("639"): return "+" + compact
    if compact.startswith("9") and len(compact) == 10: return "+63" + compact
    return compact

class LoginForm(AuthenticationForm):
    username = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"autocomplete": "email"}))
class CustomerRegistrationForm(forms.Form):
    first_name = forms.CharField(max_length=80); last_name = forms.CharField(max_length=80)
    email = forms.EmailField(widget=forms.EmailInput(attrs={"autocomplete": "email"})); phone = forms.CharField(max_length=32, validators=[PH_PHONE], widget=forms.TelInput(attrs={"autocomplete": "tel", "inputmode": "tel"}))
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "minlength": 12}), help_text="Use at least 12 characters. Avoid common passwords and personal information.")
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "minlength": 12}))
    accept_terms = forms.BooleanField(label="I accept the Terms and Privacy Policy")
    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"].strip()).lower()
        if User.objects.filter(email=email).exists(): raise forms.ValidationError("An account already exists for this email.")
        return email
    def clean_first_name(self): return normalized_text(self.cleaned_data["first_name"], "First name")
    def clean_last_name(self): return normalized_text(self.cleaned_data["last_name"], "Last name")
    def clean_phone(self): return normalize_phone(self.cleaned_data["phone"])
    def clean(self):
        data = super().clean()
        if data.get("password1") != data.get("password2"): self.add_error("password2", "Passwords do not match.")
        elif data.get("password1"): validate_password(data["password1"], user=User(email=data.get("email", "")))
        return data
class SupplierRegistrationForm(CustomerRegistrationForm):
    legal_name = forms.CharField(label="Legal business name", max_length=255)
    display_name = forms.CharField(label="Display/business name", max_length=255)
    business_address = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), max_length=500)
    business_registration_number = forms.CharField(label="Business registration number", max_length=80)
    business_phone = forms.CharField(label="Business contact phone", max_length=32, validators=[PH_PHONE], widget=forms.TelInput(attrs={"autocomplete": "tel", "inputmode": "tel"}))
    def clean_legal_name(self):
        value = normalized_text(self.cleaned_data["legal_name"], "Legal business name")
        if Supplier.objects.filter(legal_name__iexact=value).exists():
            raise forms.ValidationError("A supplier application already exists for this legal business name.")
        return value
    def clean_display_name(self): return normalized_text(self.cleaned_data["display_name"], "Display/business name")
    def clean_business_address(self): return normalized_text(self.cleaned_data["business_address"], "Business address")
    def clean_business_registration_number(self):
        value = normalized_text(self.cleaned_data["business_registration_number"], "Business registration number").upper()
        if Supplier.objects.filter(business_registration_number__iexact=value).exists():
            raise forms.ValidationError("This business registration number is already associated with an application.")
        return value
    def clean_business_phone(self): return normalize_phone(self.cleaned_data["business_phone"])
class BuiltasupplyPasswordResetForm(PasswordResetForm):
    def get_users(self, email): return User.objects.filter(email__iexact=email, account_status="ACTIVE")
