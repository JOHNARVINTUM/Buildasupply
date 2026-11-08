from collections import OrderedDict
import logging
from secrets import token_urlsafe

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from apps.carts.services import get_active_cart, validate_cart
from .forms import CheckoutSubmissionForm
from .models import MasterOrder
from .services import CheckoutFailure, checkout


logger = logging.getLogger(__name__)


CHECKOUT_SESSION_KEY = "customer_checkout_idempotency"
CHECKOUT_CART_SESSION_KEY = "customer_checkout_cart_id"
CHECKOUT_MESSAGES = {
    "CART_EMPTY": "Your cart is empty. Add supplies before checking out.",
    "DELIVERY_ADDRESS_REQUIRED": "Choose a valid delivery address before placing your order.",
    "CHECKOUT_VALIDATION_FAILED": "Some cart items changed. Review the cart and try again.",
    "IDEMPOTENCY_KEY_REUSED": "This checkout request no longer matches your cart. Review the cart and try again.",
    "PRODUCT_UNAVAILABLE": "A product is no longer available.",
    "SUPPLIER_UNAVAILABLE": "A supplier is no longer available.",
    "PRICE_CHANGED": "A product price changed. Review the cart before checkout.",
    "INSUFFICIENT_STOCK": "Stock changed before checkout. Review the cart and try again.",
}


def _customer_for(request):
    if (
        request.user.primary_role != "CUSTOMER"
        or request.user.account_status != "ACTIVE"
        or not hasattr(request.user, "customer_profile")
    ):
        raise PermissionDenied("Customer access is required.")
    return request.user.customer_profile


def _checkout_key(request, cart):
    key = request.session.get(CHECKOUT_SESSION_KEY)
    if key and request.session.get(CHECKOUT_CART_SESSION_KEY) == cart.pk:
        return key
    key = token_urlsafe(32)
    request.session[CHECKOUT_SESSION_KEY] = key
    request.session[CHECKOUT_CART_SESSION_KEY] = cart.pk
    return key


def _review_context(customer, form=None):
    cart = get_active_cart(customer)
    items = list(
        cart.items.select_related("product__supplier", "product__inventory")
        .order_by("product__supplier__display_name", "pk")
    )
    validation = validate_cart(cart)
    groups = OrderedDict()
    subtotal_minor = 0
    for item in items:
        line_total = item.quantity * item.displayed_price_minor
        group = groups.setdefault(item.product.supplier_id, {"supplier": item.product.supplier, "items": [], "subtotal_minor": 0})
        group["items"].append({"item": item, "line_total_minor": line_total})
        group["subtotal_minor"] += line_total
        subtotal_minor += line_total
    addresses = list(customer.addresses.order_by("-is_default", "pk"))
    selected_address_id = str(form["delivery_address"].value()) if form and form["delivery_address"].value() else ""
    for address in addresses:
        address.is_selected_for_checkout = str(address.pk) == selected_address_id
    return {
        "cart": cart,
        "validation": validation,
        "supplier_groups": list(groups.values()),
        "addresses": addresses,
        "subtotal_minor": subtotal_minor,
        "discount_minor": 0,
        "tax_minor": 0,
        "platform_fee_minor": 0,
        "delivery_fee_minor": 0,
        "total_minor": subtotal_minor,
        "form": form,
    }


@login_required
def checkout_page(request):
    customer = _customer_for(request)
    cart = get_active_cart(customer)
    key = _checkout_key(request, cart)
    initial = {"idempotency_key": key}
    default_address = customer.addresses.filter(is_default=True).first() or customer.addresses.first()
    if default_address:
        initial["delivery_address"] = default_address.pk
    form = CheckoutSubmissionForm(customer=customer, initial=initial)
    return render(request, "orders/checkout.html", _review_context(customer, form))


@login_required
def checkout_submit(request):
    if request.method != "POST":
        return redirect("shop-checkout")
    customer = _customer_for(request)
    cart = get_active_cart(customer)
    expected_key = request.session.get(CHECKOUT_SESSION_KEY) or _checkout_key(request, cart)
    form = CheckoutSubmissionForm(request.POST, customer=customer)
    if form.is_valid() and form.cleaned_data["idempotency_key"] == expected_key:
        try:
            result = checkout(
                customer=customer,
                idempotency_key=expected_key,
                address_id=form.cleaned_data["delivery_address"].pk,
            )
        except CheckoutFailure as error:
            code = error.message_dict.get("code", "CHECKOUT_VALIDATION_FAILED")
            if isinstance(code, list):
                code = code[0]
            messages.error(request, CHECKOUT_MESSAGES.get(code, "Checkout could not be completed. Please review your order and try again."))
            if code == "CHECKOUT_VALIDATION_FAILED":
                for issue in error.message_dict.get("errors", []):
                    if isinstance(issue, dict):
                        messages.error(request, f"{issue['product']}: {CHECKOUT_MESSAGES.get(issue['code'], issue['code'])}")
        except Exception:
            logger.exception("Unexpected customer checkout failure")
            messages.error(request, "Checkout could not be completed. Please try again or review your cart.")
        else:
            messages.success(request, "Order created. Payment is still pending.")
            return redirect("shop-order-confirmation", pk=result["master_order_id"])
    elif form.is_valid():
        form.add_error(None, "Your checkout session expired. Review your order and submit again.")
    return render(request, "orders/checkout.html", _review_context(customer, form), status=400)


def _owned_order(customer, pk):
    return get_object_or_404(
        MasterOrder.objects.filter(customer=customer)
        .prefetch_related("supplier_orders__items", "supplier_orders__delivery", "financial_lines"),
        pk=pk,
    )


@login_required
def order_confirmation(request, pk):
    order = _owned_order(_customer_for(request), pk)
    return render(request, "orders/confirmation.html", {"order": order, "delivery": order.supplier_orders.first().delivery})


@login_required
def order_detail(request, pk):
    order = _owned_order(_customer_for(request), pk)
    return render(request, "orders/detail.html", {"order": order, "delivery": order.supplier_orders.first().delivery})


@login_required
def order_history(request):
    customer = _customer_for(request)
    orders = MasterOrder.objects.filter(customer=customer).order_by("-placed_at")
    return render(request, "orders/history.html", {"orders": orders})
