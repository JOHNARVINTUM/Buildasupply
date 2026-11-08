from django.db import transaction

from .models import CustomerAddress, CustomerProfile


def _locked_customer(customer):
    return CustomerProfile.objects.select_for_update().get(pk=customer.pk)


@transaction.atomic
def save_address(*, customer, address, form):
    """Create or update an address while preserving one useful default address."""
    customer = _locked_customer(customer)
    addresses = CustomerAddress.objects.select_for_update().filter(customer=customer)
    was_default = bool(address.pk and address.is_default)
    address = form.save(commit=False)
    address.customer = customer
    if address.is_default or not addresses.exists():
        addresses.filter(is_default=True).exclude(pk=address.pk).update(is_default=False)
        address.is_default = True
    elif was_default:
        address.save()
        replacement = addresses.exclude(pk=address.pk).order_by("pk").first()
        if replacement:
            replacement.is_default = True
            replacement.save(update_fields=["is_default"])
        return address
    address.save()
    return address


@transaction.atomic
def set_default_address(*, customer, address):
    customer = _locked_customer(customer)
    addresses = CustomerAddress.objects.select_for_update().filter(customer=customer)
    address = addresses.get(pk=address.pk)
    addresses.filter(is_default=True).exclude(pk=address.pk).update(is_default=False)
    if not address.is_default:
        address.is_default = True
        address.save(update_fields=["is_default"])
    return address


@transaction.atomic
def delete_address(*, customer, address):
    customer = _locked_customer(customer)
    addresses = CustomerAddress.objects.select_for_update().filter(customer=customer)
    address = addresses.get(pk=address.pk)
    was_default = address.is_default
    address.delete()
    if was_default:
        replacement = addresses.order_by("pk").first()
        if replacement:
            replacement.is_default = True
            replacement.save(update_fields=["is_default"])
