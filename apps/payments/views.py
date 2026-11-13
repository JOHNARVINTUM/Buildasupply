import logging
from secrets import token_urlsafe

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from apps.orders.models import MasterOrder
from .forms import DemoPaymentForm
from .models import Payment
from .adapters import get_adapter
from .services import PaymentFailure, initiate_payment, process_pesoway_webhook, select_cod


logger = logging.getLogger(__name__)
PAYMENT_KEY_PREFIX = "customer_payment_idempotency:"
PAYMENT_MESSAGES = {
    "ORDER_ALREADY_PAID": "This order has already been paid.",
    "ORDER_NOT_PAYMENT_ELIGIBLE": "This order is not eligible for payment.",
    "NO_ACTIVE_RESERVATIONS": "The payment hold for this order expired. Review your cart and create a new order.",
    "PAYMENT_PROVIDER_MISMATCH": "This order already has a payment attempt with a different provider.",
    "IDEMPOTENCY_REQUIRED": "Please reload the payment page and try again.",
}


def _customer_for(request):
    if (
        request.user.primary_role not in {"CUSTOMER", "STAFF_BUYER"}
        or request.user.account_status != "ACTIVE"
        or not hasattr(request.user, "customer_profile")
    ):
        raise PermissionDenied("Customer access is required.")
    return request.user.customer_profile


def _owned_order(customer, pk):
    return get_object_or_404(MasterOrder, pk=pk, customer=customer)


def _payment_key(request, order):
    key_name = f"{PAYMENT_KEY_PREFIX}{order.pk}"
    key = request.session.get(key_name)
    if not key:
        key = token_urlsafe(32)
        request.session[key_name] = key
    return key


def _payment_context(order, form):
    return {"order": order, "form": form, "existing_payment": order.payments.filter(status__in=["PENDING", "AUTHORIZED"]).first()}


@login_required
def payment_select(request, order_id):
    customer = _customer_for(request)
    order = _owned_order(customer, order_id)
    existing = order.payments.filter(status__in=["PENDING", "AUTHORIZED"]).first()
    if existing and request.method == "GET":
        if existing.provider_code == "pesoway" and existing.provider_reference:
            try:
                return redirect(get_adapter("pesoway").checkout_url(existing.provider_reference))
            except ValueError:
                pass
        return redirect("shop-payment-instructions", pk=existing.pk)
    key = _payment_key(request, order)
    if request.method == "POST":
        form = DemoPaymentForm(request.POST)
        if form.is_valid() and form.cleaned_data["idempotency_key"] == key:
            try:
                result = initiate_payment(
                    customer=customer,
                    order=order,
                    provider_code="demo",
                    method_category=form.cleaned_data["method_category"],
                    idempotency_key=key,
                )
            except PaymentFailure as error:
                code = error.message_dict.get("code", "")
                if isinstance(code, list):
                    code = code[0]
                messages.error(request, PAYMENT_MESSAGES.get(code, "Payment could not be started. Please review your order and try again."))
            except ValueError:
                messages.error(request, "The demo payment provider is unavailable in this environment.")
            except Exception:
                logger.exception("Unexpected payment initiation failure")
                messages.error(request, "Payment could not be started. Please try again.")
            else:
                return redirect("shop-payment-instructions", pk=result["payment_id"])
        elif form.is_valid():
            form.add_error(None, "Your payment session expired. Reload the page and try again.")
    else:
        form = DemoPaymentForm(initial={"idempotency_key": key})
    return render(request, "payments/select.html", _payment_context(order, form), status=400 if request.method == "POST" and form.errors else 200)


@login_required
def pesoway_start(request, order_id):
    """Create a backend-owned PesoWay intent, then send the buyer to its hosted simulation."""
    if request.method != "POST":
        return redirect("shop-payment-select", order_id=order_id)
    customer = _customer_for(request)
    order = _owned_order(customer, order_id)
    try:
        result = initiate_payment(
            customer=customer,
            order=order,
            provider_code="pesoway",
            method_category="HOSTED_CHECKOUT",
            idempotency_key=_payment_key(request, order),
            return_url=request.build_absolute_uri(reverse("pesoway-complete")),
        )
    except PaymentFailure as error:
        code = error.message_dict.get("code", "")
        if isinstance(code, list):
            code = code[0]
        messages.error(request, PAYMENT_MESSAGES.get(code, "PesoWay payment could not be started. Please review your order and try again."))
        return redirect("shop-payment-select", order_id=order.pk)
    except ValueError:
        logger.exception("PesoWay initiation failed")
        messages.error(request, "PesoWay is unavailable. Please try again later or choose another payment option.")
        return redirect("shop-payment-select", order_id=order.pk)
    return redirect(result["instruction_url"])


@login_required
def cod_select(request, order_id):
    """Select COD for an already-created, reservation-backed customer order."""
    if request.method != "POST":
        return redirect("shop-order-confirmation", pk=order_id)
    customer = _customer_for(request)
    order = _owned_order(customer, order_id)
    try:
        select_cod(customer=customer, order=order)
    except PaymentFailure as error:
        code = error.message_dict.get("code", "")
        if isinstance(code, list):
            code = code[0]
        messages.error(request, {
            "COD_NOT_ELIGIBLE": "Cash on delivery is no longer available for this order.",
            "ONLINE_PAYMENT_ALREADY_INITIATED": "An online payment was already started for this order.",
            "ORDER_ACCESS_DENIED": "You cannot select a payment method for this order.",
        }.get(code, "Cash on delivery could not be selected. Please review your order."))
    else:
        messages.success(request, "Cash on delivery selected. Payment will be collected for each supplier order upon delivery.")
    return redirect("shop-order-confirmation", pk=order.pk)


def _owned_payment(customer, pk):
    return get_object_or_404(Payment.objects.select_related("master_order"), pk=pk, master_order__customer=customer)


@login_required
def payment_instructions(request, pk):
    payment = _owned_payment(_customer_for(request), pk)
    return render(request, "payments/instructions.html", {"payment": payment, "instruction_url": request.build_absolute_uri(f"/shop/payments/{payment.pk}/")})


@login_required
def payment_status(request, pk):
    payment = _owned_payment(_customer_for(request), pk)
    attempts = payment.attempts.order_by("-created_at")
    return render(request, "payments/status.html", {"payment": payment, "attempts": attempts})


@login_required
def pesoway_complete(request):
    """Navigation-only return endpoint; the webhook remains the payment authority."""
    customer = _customer_for(request)
    payment_intent = request.GET.get("payment_intent", "")
    payment = get_object_or_404(
        Payment.objects.select_related("master_order"),
        provider_code="pesoway",
        provider_reference=payment_intent,
        master_order__customer=customer,
    )
    return render(request, "payments/pesoway_complete.html", {"payment": payment})


@csrf_exempt
def pesoway_webhook(request):
    """Public provider endpoint. Errors intentionally reveal no payment information."""
    if request.method != "POST":
        return HttpResponse(status=405)
    try:
        process_pesoway_webhook(raw_body=request.body, headers=request.headers)
    except PaymentFailure as error:
        code = error.message_dict.get("code", "")
        if isinstance(code, list):
            code = code[0]
        logger.warning("PesoWay webhook rejected: %s", code)
        return HttpResponse(status=400 if code == "INVALID_WEBHOOK_SIGNATURE" else 500)
    except Exception:
        logger.exception("Unexpected PesoWay webhook processing failure")
        return HttpResponse(status=500)
    return HttpResponse(status=204)
