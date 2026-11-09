from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.permissions import can_manage_fulfillment
from apps.payments.models import CODCommitment, CODException
from apps.payments.services import (
    PaymentFailure,
    accept_cod_supplier_order,
    record_cod_collection,
    report_cod_delivery_exception,
)
from .forms import CODCollectionForm, CODExceptionForm, DispatchSupplierOrderForm
from .models import SupplierOrder
from .services import transition_supplier_order


COD_STATUSES = {
    "incoming": "PENDING_SUPPLIER",
    "accepted": "CONFIRMED",
    "preparing": "PREPARING",
    "ready": "READY_FOR_DELIVERY",
    "dispatched": "SHIPPED",
    "delivered": "DELIVERED",
    "completed": "COMPLETED",
}


def _active_supplier_ids(request):
    if not request.user.is_authenticated or request.user.account_status != "ACTIVE":
        raise PermissionDenied("An active supplier account is required.")
    return request.user.supplier_memberships.filter(status="ACTIVE", supplier__approval_status="APPROVED").values_list("supplier_id", flat=True)


def _supplier_order_or_404(request, pk):
    return get_object_or_404(
        SupplierOrder.objects.filter(supplier_id__in=_active_supplier_ids(request), master_order__cod_commitment__isnull=False)
        .select_related("master_order", "delivery")
        .prefetch_related("items__product__images", "cod_exceptions"),
        pk=pk,
    )


def _fulfillment_order_or_403(request, pk):
    order = _supplier_order_or_404(request, pk)
    if not can_manage_fulfillment(request.user, order.supplier):
        raise PermissionDenied("Supplier fulfillment access is required.")
    return order


def _is_cod(order):
    try:
        return order.master_order.cod_commitment.status == "ACTIVE"
    except CODCommitment.DoesNotExist:
        return False


def _service_error(request, error):
    detail = getattr(error, "message_dict", None) or getattr(error, "messages", None) or str(error)
    if isinstance(detail, dict):
        detail = detail.get("code", "The order could not be updated.")
    if isinstance(detail, (list, tuple)):
        detail = "; ".join(str(item) for item in detail)
    messages.error(request, str(detail).replace("_", " ").capitalize())


@login_required
def cod_order_dashboard(request):
    status_filter = request.GET.get("status", "")
    orders = SupplierOrder.objects.filter(supplier_id__in=_active_supplier_ids(request), master_order__cod_commitment__isnull=False).select_related("master_order", "delivery").prefetch_related("items", "cod_exceptions").order_by("-master_order__placed_at")
    if status_filter in COD_STATUSES:
        orders = orders.filter(status=COD_STATUSES[status_filter])
    elif status_filter == "exceptions":
        orders = orders.filter(cod_exceptions__status__in=[CODException.Status.FAILED_DELIVERY, CODException.Status.DISPUTED]).distinct()
    page = Paginator(orders, 20).get_page(request.GET.get("page"))
    for order in page:
        order.is_cod = _is_cod(order)
        order.exception_open = any(item.status in {CODException.Status.FAILED_DELIVERY, CODException.Status.DISPUTED} for item in order.cod_exceptions.all())
        order.total_php = order.total_minor / 100
    return render(request, "orders/supplier_cod_dashboard.html", {"page": page, "status_filter": status_filter, "status_filters": COD_STATUSES})


@login_required
def cod_order_detail(request, pk):
    order = _supplier_order_or_404(request, pk)
    order.is_cod = _is_cod(order)
    order.can_fulfill = can_manage_fulfillment(request.user, order.supplier)
    order.total_php = order.total_minor / 100
    for item in order.items.all():
        item.unit_price_php = item.unit_price_minor / 100
        item.line_total_php = item.line_total_minor / 100
    collection_form = CODCollectionForm(initial={"amount_minor": order.total_minor, "currency": order.currency})
    return render(request, "orders/supplier_cod_detail.html", {
        "supplier_order": order,
        "collection_form": collection_form,
        "dispatch_form": DispatchSupplierOrderForm(),
        "exception_form": CODExceptionForm(),
        "open_exceptions": [item for item in order.cod_exceptions.all() if item.status in {CODException.Status.FAILED_DELIVERY, CODException.Status.DISPUTED}],
    })


def _post_only(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])


@login_required
def accept_cod_order(request, pk):
    denied = _post_only(request)
    if denied: return denied
    order = _fulfillment_order_or_403(request, pk)
    try:
        accept_cod_supplier_order(supplier_order=order, actor=request.user)
        messages.success(request, "Order accepted. You can now begin preparation.")
    except (PaymentFailure, ValidationError, PermissionDenied) as error:
        _service_error(request, error)
    return redirect("supplier-cod-order-detail", pk=order.pk)


def _transition(request, pk, status, success, delivery_data=None):
    denied = _post_only(request)
    if denied: return denied
    order = _fulfillment_order_or_403(request, pk)
    try:
        transition_supplier_order(supplier_order=order, actor=request.user, next_status=status, delivery_data=delivery_data)
        messages.success(request, success)
    except (ValidationError, PermissionDenied) as error:
        _service_error(request, error)
    return redirect("supplier-cod-order-detail", pk=order.pk)


@login_required
def prepare_order(request, pk):
    return _transition(request, pk, "PREPARING", "Order marked as preparing.")


@login_required
def ready_order(request, pk):
    return _transition(request, pk, "READY_FOR_DELIVERY", "Order is ready for delivery.")


@login_required
def dispatch_order(request, pk):
    denied = _post_only(request)
    if denied: return denied
    order = _fulfillment_order_or_403(request, pk)
    form = DispatchSupplierOrderForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Enter a delivery method and tracking or delivery reference before dispatching.")
        return redirect("supplier-cod-order-detail", pk=order.pk)
    return _transition(request, pk, "SHIPPED", "Order dispatched.", form.cleaned_data)


@login_required
def deliver_order(request, pk):
    return _transition(request, pk, "DELIVERED", "Order marked as delivered. Record the cash collection when received.")


@login_required
def record_collection(request, pk):
    denied = _post_only(request)
    if denied: return denied
    order = _fulfillment_order_or_403(request, pk)
    form = CODCollectionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Enter the required collection reference and valid collection details.")
        return redirect("supplier-cod-order-detail", pk=order.pk)
    try:
        record_cod_collection(supplier_order=order, actor=request.user, amount_minor=form.cleaned_data["amount_minor"], currency=form.cleaned_data["currency"], collection_reference=form.cleaned_data["collection_reference"], evidence_metadata=form.evidence_metadata())
        messages.success(request, "Cash collection recorded. Awaiting customer receipt confirmation.")
    except (PaymentFailure, ValidationError, PermissionDenied) as error:
        _service_error(request, error)
    return redirect("supplier-cod-order-detail", pk=order.pk)


@login_required
def report_exception(request, pk):
    denied = _post_only(request)
    if denied: return denied
    order = _fulfillment_order_or_403(request, pk)
    form = CODExceptionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Provide a failed-delivery or dispute reason.")
        return redirect("supplier-cod-order-detail", pk=order.pk)
    try:
        report_cod_delivery_exception(supplier_order=order, actor=request.user, status=form.cleaned_data["status"], reason=form.cleaned_data["reason"])
        messages.success(request, "Delivery exception reported for superadmin review. Inventory and settlement were not changed.")
    except (PaymentFailure, ValidationError, PermissionDenied) as error:
        _service_error(request, error)
    return redirect("supplier-cod-order-detail", pk=order.pk)
