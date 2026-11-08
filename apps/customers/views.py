from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models.deletion import ProtectedError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from .forms import CustomerAddressForm
from .models import CustomerAddress
from .services import delete_address, save_address, set_default_address


def _customer_for(request):
    if (
        request.user.primary_role != "CUSTOMER"
        or request.user.account_status != "ACTIVE"
        or not hasattr(request.user, "customer_profile")
    ):
        raise PermissionDenied("Customer access is required.")
    return request.user.customer_profile


def _owned_address(customer, pk):
    return get_object_or_404(CustomerAddress, pk=pk, customer=customer)


@login_required
def address_list(request):
    customer = _customer_for(request)
    return render(request, "customers/address_list.html", {"addresses": customer.addresses.order_by("-is_default", "pk")})


@login_required
def address_create(request):
    customer = _customer_for(request)
    form = CustomerAddressForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        save_address(customer=customer, address=CustomerAddress(customer=customer), form=form)
        messages.success(request, "Delivery address added.")
        return redirect("customers:address-list")
    return render(request, "customers/address_form.html", {"form": form, "page_title": "Add delivery address"})


@login_required
def address_edit(request, pk):
    customer = _customer_for(request)
    address = _owned_address(customer, pk)
    form = CustomerAddressForm(request.POST or None, instance=address)
    if request.method == "POST" and form.is_valid():
        save_address(customer=customer, address=address, form=form)
        messages.success(request, "Delivery address updated.")
        return redirect("customers:address-list")
    return render(request, "customers/address_form.html", {"form": form, "address": address, "page_title": "Edit delivery address"})


@login_required
def address_delete(request, pk):
    customer = _customer_for(request)
    address = _owned_address(customer, pk)
    if request.method == "POST":
        try:
            delete_address(customer=customer, address=address)
        except ProtectedError:
            messages.error(request, "This address is protected by a related record and cannot be deleted.")
        else:
            messages.success(request, "Delivery address deleted.")
        return redirect("customers:address-list")
    return render(request, "customers/address_confirm_delete.html", {"address": address})


@login_required
def address_set_default(request, pk):
    if request.method != "POST":
        raise Http404
    customer = _customer_for(request)
    address = _owned_address(customer, pk)
    set_default_address(customer=customer, address=address)
    messages.success(request, "Default delivery address updated.")
    return redirect("customers:address-list")
