from django.contrib import messages
from django.contrib.auth import login, logout
from django.core.cache import cache
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordResetConfirmView, PasswordResetView
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.db import transaction
from apps.audit.services import log_action
from apps.customers.models import CustomerProfile
from .forms import BuiltasupplyPasswordResetForm, CustomerRegistrationForm, LoginForm, ProfileForm, SupplierRegistrationForm
from .services import register_customer, register_supplier
def _limited(request, bucket, limit, window):
    key = f"auth-rate:{bucket}:{request.META.get('REMOTE_ADDR', 'unknown')}"
    if cache.add(key, 1, window): return False
    try: return cache.incr(key) > limit
    except ValueError: return False

def login_view(request):
    form = LoginForm(request, data=request.POST or None)
    if request.method == "POST" and _limited(request, "login", 10, 900): form.add_error(None, "Too many sign-in attempts. Please try again later.")
    elif request.method == "POST" and form.is_valid(): login(request, form.get_user()); return redirect("home")
    return render(request, "accounts/login.html", {"form": form})
def logout_view(request): logout(request); return redirect("accounts:login")
def customer_register(request):
    form = CustomerRegistrationForm(request.POST or None)
    if request.method == "POST" and _limited(request, "customer-registration", 5, 3600): form.add_error(None, "Too many registration attempts. Please try again later.")
    elif request.method == "POST" and form.is_valid():
        user = register_customer(**form.cleaned_data)
        request.session["registration_success"] = {"kind": "customer", "name": user.customer_profile.full_name.split()[0]}
        return redirect("accounts:registration-success")
    return render(request, "accounts/register.html", {"form": form, "kind": "Customer"})
def supplier_register(request):
    form = SupplierRegistrationForm(request.POST or None)
    if request.method == "POST" and _limited(request, "supplier-registration", 5, 3600): form.add_error(None, "Too many registration attempts. Please try again later.")
    elif request.method == "POST" and form.is_valid():
        user, _ = register_supplier(**form.cleaned_data)
        request.session["registration_success"] = {"kind": "supplier", "name": user.email}
        return redirect("accounts:registration-success")
    return render(request, "accounts/register.html", {"form": form, "kind": "Supplier"})
@login_required
def profile(request):
    form = ProfileForm(request.POST if request.method == "POST" else None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            request.user.full_name = form.cleaned_data["full_name"]
            request.user.phone = form.cleaned_data["phone"]
            request.user.save(update_fields=["full_name", "phone", "updated_at"])
            if request.user.primary_role in {"CUSTOMER", "STAFF_BUYER"}:
                CustomerProfile.objects.update_or_create(user=request.user, defaults={"full_name": request.user.full_name, "phone": request.user.phone})
            log_action(actor=request.user, action="PROFILE_UPDATED", target=request.user)
        messages.success(request, "Your profile has been updated.")
        return redirect("accounts:profile")
    layout = {"CUSTOMER": "customers/layout.html", "STAFF_BUYER": "customers/layout.html", "SUPPLIER": "suppliers/layout.html", "SUPERADMIN": "operations/layout.html"}.get(request.user.primary_role, "customers/layout.html")
    return render(request, "accounts/profile.html", {"form": form, "profile_layout": layout})
def registration_success(request):
    context = request.session.pop("registration_success", None)
    if not context: return redirect("accounts:register")
    return render(request, "accounts/registration_success.html", context)
def password_reset(request):
    if request.method == "POST" and _limited(request, "password-reset", 5, 3600):
        messages.error(request, "Too many password reset requests. Please try again later.")
        return redirect("accounts:password-reset")
    return PasswordResetView.as_view(form_class=BuiltasupplyPasswordResetForm, template_name="accounts/password_reset.html", email_template_name="accounts/password_reset_email.txt", success_url=reverse_lazy("accounts:password-reset-done"))(request)
def password_reset_done(request): return render(request, "accounts/password_reset_done.html")
password_reset_confirm = PasswordResetConfirmView.as_view(template_name="accounts/password_reset_confirm.html", success_url=reverse_lazy("accounts:login"))
