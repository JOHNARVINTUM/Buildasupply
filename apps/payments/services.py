"""Payment operations.

Lock hierarchy for payment/order work is always:
MasterOrder -> Payment -> SupplierOrder -> InventoryReservation -> Inventory.
This is deliberately shared by confirmation, expiry, and reconciliation work.
"""
import hashlib
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.audit.services import log_action
from apps.catalog.services import is_product_purchasable
from apps.inventory.models import Inventory, InventoryMovement, InventoryReservation
from apps.orders.models import MasterOrder, SupplierOrder

from .adapters import get_adapter
from .models import (
    CODCollection, CODCommitment, CODException, CODReceiptConfirmation,
    Payment, PaymentAttempt, PaymentEvent, PaymentReconciliation,
    PaymentReconciliationHistory, Refund, RefundAllocation, RefundEvent, WebhookEvent,
)


class PaymentFailure(ValidationError):
    pass


def _lock_order(payment_id):
    """Acquire the first two locks in the documented global order."""
    order_id = Payment.objects.values_list("master_order_id", flat=True).get(pk=payment_id)
    order = MasterOrder.objects.select_for_update().get(pk=order_id)
    payment = Payment.objects.select_for_update().get(pk=payment_id)
    return order, payment


def _lock_supplier_orders(master_order):
    return list(SupplierOrder.objects.select_for_update().filter(master_order=master_order).order_by("pk"))


def _lock_active_reservations(master_order):
    """Lock reservations then inventories in the global order after supplier orders."""
    _lock_supplier_orders(master_order)
    reservations = list(
        InventoryReservation.objects.select_for_update()
        .filter(supplier_order__master_order=master_order, status="ACTIVE")
        .order_by("inventory_id", "pk")
    )
    inventories = {
        inventory.id: inventory
        for inventory in Inventory.objects.select_for_update()
        .filter(id__in=[reservation.inventory_id for reservation in reservations])
        .order_by("pk")
    }
    return reservations, inventories


@transaction.atomic
def initiate_payment(*, customer, order, provider_code, method_category, idempotency_key, return_url=""):
    if not idempotency_key:
        raise PaymentFailure({"code": "IDEMPOTENCY_REQUIRED"})
    order = MasterOrder.objects.select_for_update().get(pk=order.pk)
    if order.customer_id != customer.id:
        raise PaymentFailure({"code": "ORDER_ACCESS_DENIED"})
    if order.payment_status == "PAID":
        raise PaymentFailure({"code": "ORDER_ALREADY_PAID"})
    if order.status != "PENDING_PAYMENT" or order.payment_status != "PENDING":
        raise PaymentFailure({"code": "ORDER_NOT_PAYMENT_ELIGIBLE"})
    if not InventoryReservation.objects.filter(supplier_order__master_order=order, status="ACTIVE").exists():
        raise PaymentFailure({"code": "NO_ACTIVE_RESERVATIONS"})
    payment = Payment.objects.filter(master_order=order, status__in=["PENDING", "AUTHORIZED"]).first()
    if not payment:
        payment = Payment.objects.create(master_order=order, internal_reference=f"PAY-{order.order_number}-{uuid.uuid4().hex[:10]}", provider_code=provider_code, provider_merchant_reference=f"buildasupply-order-{order.id}" if provider_code == "pesoway" else "", method_category=method_category, amount_minor=order.total_minor, currency=order.currency)
    if payment.provider_code != provider_code:
        raise PaymentFailure({"code": "PAYMENT_PROVIDER_MISMATCH"})
    old = payment.attempts.filter(idempotency_key=idempotency_key).first()
    if old:
        result = {"payment_id": str(payment.id), "attempt_id": old.id, "status": payment.status, "idempotent": True}
        if provider_code == "pesoway" and payment.provider_reference:
            result["instruction_url"] = get_adapter(provider_code).checkout_url(payment.provider_reference)
        return result
    active_attempt = payment.attempts.filter(status="PENDING").first()
    if active_attempt:
        result = {"payment_id": str(payment.id), "attempt_id": active_attempt.id, "status": payment.status, "pending_attempt_reused": True}
        if provider_code == "pesoway" and payment.provider_reference:
            result["instruction_url"] = get_adapter(provider_code).checkout_url(payment.provider_reference)
        return result
    result = get_adapter(provider_code).create_payment(payment=payment, idempotency_key=idempotency_key, return_url=return_url)
    payment.provider_reference = result["provider_reference"]
    payment.provider_merchant_reference = result.get("merchant_reference", payment.provider_merchant_reference)
    payment.provider_status = result.get("provider_status", payment.provider_status)
    payment.save(update_fields=["provider_reference", "provider_merchant_reference", "provider_status", "updated_at"])
    attempt = PaymentAttempt.objects.create(payment=payment, provider_code=provider_code, provider_attempt_reference=result["attempt_reference"], idempotency_key=idempotency_key, method_category=method_category, status=result["status"])
    return {"payment_id": str(payment.id), "attempt_id": attempt.id, "status": payment.status, "instruction_url": result["instruction_url"]}


@transaction.atomic
def consume_reservations(*, master_order, actor=None):
    # MasterOrder -> SupplierOrder -> InventoryReservation -> Inventory.
    master_order = MasterOrder.objects.select_for_update().get(pk=master_order.pk)
    reservations, inventories = _lock_active_reservations(master_order)
    if not reservations:
        raise PaymentFailure({"code": "NO_ACTIVE_RESERVATIONS"})
    for reservation in reservations:
        inventory = inventories[reservation.inventory_id]
        if inventory.reserved_quantity < reservation.quantity:
            raise PaymentFailure({"code": "RESERVATION_INCONSISTENT"})
        inventory.reserved_quantity -= reservation.quantity
        inventory.sold_quantity += reservation.quantity
        inventory.save(update_fields=["reserved_quantity", "sold_quantity", "updated_at"])
        reservation.status = "CONSUMED"
        reservation.save(update_fields=["status", "updated_at"])
        InventoryMovement.objects.create(inventory=inventory, movement_type="SALE", quantity_delta=-reservation.quantity, reason=f"Payment for {master_order.order_number}", actor=actor, reference_type="orders.SupplierOrder", reference_id=reservation.supplier_order_id)


@transaction.atomic
def release_reservations(*, master_order, actor=None, expired=False):
    # MasterOrder -> SupplierOrder -> InventoryReservation -> Inventory.
    master_order = MasterOrder.objects.select_for_update().get(pk=master_order.pk)
    reservations, inventories = _lock_active_reservations(master_order)
    for reservation in reservations:
        inventory = inventories[reservation.inventory_id]
        inventory.available_quantity += reservation.quantity
        inventory.reserved_quantity -= reservation.quantity
        inventory.status = "ACTIVE"
        inventory.save(update_fields=["available_quantity", "reserved_quantity", "status", "updated_at"])
        reservation.status = "EXPIRED" if expired else "RELEASED"
        reservation.save(update_fields=["status", "updated_at"])
        InventoryMovement.objects.create(inventory=inventory, movement_type="RESERVATION_RELEASE", quantity_delta=reservation.quantity, reason="Payment reservation released", actor=actor, reference_type="orders.SupplierOrder", reference_id=reservation.supplier_order_id)


def _record_reconciliation(*, payment, order, webhook_event, event_data):
    reconciliation, created = PaymentReconciliation.objects.get_or_create(
        webhook_event=webhook_event,
        defaults={
            "payment": payment,
            "master_order": order,
            "provider_code": webhook_event.provider_code,
            "provider_event_id": webhook_event.provider_event_id,
            "amount_minor": payment.amount_minor,
            "currency": payment.currency,
            "provider_amount_minor": event_data.get("amount_minor"),
            "provider_currency": event_data.get("currency", ""),
            "provider_event_at": event_data.get("occurred_at"),
        },
    )
    if created:
        PaymentReconciliationHistory.objects.create(reconciliation=reconciliation, action="LATE_PAYMENT_RECORDED", metadata={"payment_status": payment.status, "order_status": order.status})
        from apps.notifications.services import emit, superadmin_recipient_ids
        emit("payment.reconciliation_required",reconciliation,{"recipient_ids":superadmin_recipient_ids(),"order_number":order.order_number,"link":"/operations/cod/reconciliations/","priority":"HIGH"})
        log_action(actor=None, action="LATE_PAYMENT_REQUIRES_RECONCILIATION", target=reconciliation, after={"payment_id": str(payment.id), "order_id": str(order.id), "provider_event_id": webhook_event.provider_event_id})
    return reconciliation


def _finalize_paid_payment(*, payment, order):
    """Consume already-valid active reservations, then make the normal paid transition."""
    consume_reservations(master_order=order)
    payment.status = "PAID"
    payment.paid_minor = payment.amount_minor
    payment.paid_at = timezone.now()
    payment.save(update_fields=["status", "paid_minor", "paid_at", "updated_at"])
    order.payment_status = "PAID"
    order.status = "PROCESSING"
    order.save(update_fields=["payment_status", "status"])
    for supplier_order in _lock_supplier_orders(order):
        supplier_order.status = "PENDING_SUPPLIER"
        supplier_order.save(update_fields=["status"])
    from apps.wallets.services import post_payment_earnings
    post_payment_earnings(order)
    from apps.notifications.services import emit
    emit("payment.succeeded", payment, {"recipient_ids": [str(order.customer.user_id)], "order_number": order.order_number, "link": f"/shop/payments/{payment.id}/"})
    log_action(actor=None, action="PAYMENT_CONFIRMED", target=payment, after={"status": "PAID"})


@transaction.atomic
def confirm_payment(*, payment, provider_event_id, event_type, normalized_status, webhook_event=None, event_data=None):
    """Confirm a provider event. A late PAID event is durable but never auto-fulfilled."""
    event_data = event_data or {}
    order, payment = _lock_order(payment.pk)
    if PaymentEvent.objects.filter(payment=payment, provider_event_id=provider_event_id).exists():
        return {"payment": payment, "reconciliation": getattr(webhook_event, "reconciliation", None)}
    digest = hashlib.sha256((provider_event_id + normalized_status).encode()).hexdigest()
    PaymentEvent.objects.create(payment=payment, webhook_event=webhook_event, provider_event_id=provider_event_id, event_type=event_type, normalized_status=normalized_status, payload_digest=digest)
    if normalized_status == "PAID":
        if payment.status == "PAID":
            return {"payment": payment, "reconciliation": None}
        if payment.amount_minor != order.total_minor or payment.currency != order.currency:
            raise PaymentFailure({"code": "PAYMENT_AMOUNT_MISMATCH"})
        active_exists = InventoryReservation.objects.filter(supplier_order__master_order=order, status="ACTIVE").exists()
        if order.status != "PENDING_PAYMENT" or order.payment_status != "PENDING" or not active_exists:
            if not webhook_event:
                raise PaymentFailure({"code": "NO_ACTIVE_RESERVATIONS"})
            reconciliation = _record_reconciliation(payment=payment, order=order, webhook_event=webhook_event, event_data=event_data)
            return {"payment": payment, "reconciliation": reconciliation}
        _finalize_paid_payment(payment=payment, order=order)
        payment.attempts.filter(status="PENDING").update(status="COMPLETED", completed_at=timezone.now())
    elif normalized_status in {"FAILED", "CANCELLED", "EXPIRED"} and payment.status != "PAID":
        release_reservations(master_order=order, expired=True)
        payment.status = normalized_status
        payment.save(update_fields=["status", "updated_at"])
        order.payment_status = normalized_status
        order.status = "CANCELLED"
        order.save(update_fields=["payment_status", "status"])
        SupplierOrder.objects.filter(master_order=order).exclude(status="CANCELLED").update(status="CANCELLED")
        payment.attempts.filter(status="PENDING").update(status="FAILED", completed_at=timezone.now(), failure_code=f"PROVIDER_{normalized_status}")
        from apps.notifications.services import emit
        emit("payment.failed",payment,{"recipient_ids":[str(order.customer.user_id)],"order_number":order.order_number,"link":f"/shop/payments/{payment.id}/","priority":"HIGH"})
        log_action(actor=None, action="PAYMENT_FAILED_ORDER_CANCELLED", target=payment, after={"status": normalized_status, "order_status": "CANCELLED"})
    return {"payment": payment, "reconciliation": None}


@transaction.atomic
def process_webhook(*, provider_code, raw_body, headers):
    data = get_adapter(provider_code).verify_webhook(raw_body=raw_body, headers=headers)
    if not data:
        raise PaymentFailure({"code": "INVALID_WEBHOOK_SIGNATURE"})
    event, created = WebhookEvent.objects.get_or_create(provider_code=provider_code, provider_event_id=data["event_id"], defaults={"verified": True, "raw_body": raw_body.decode()})
    if not created:
        reconciliation = PaymentReconciliation.objects.filter(webhook_event=event).first()
        return {"duplicate": True, "reconciliation_required": bool(reconciliation), "reconciliation_id": str(reconciliation.id) if reconciliation else None, "payment_id": str(reconciliation.payment_id) if reconciliation else None}
    payment = Payment.objects.filter(provider_code=provider_code, provider_reference=data["provider_reference"]).first()
    if not payment:
        event.processing_status = "UNKNOWN_PAYMENT"
        event.processed_at = timezone.now()
        event.save(update_fields=["processing_status", "processed_at"])
        raise PaymentFailure({"code": "UNKNOWN_PAYMENT"})
    if data.get("merchant_reference") != payment.internal_reference:
        log_action(actor=None, action="PAYMENT_WEBHOOK_REFERENCE_REJECTED", target=payment, after={"provider_event_id":data["event_id"]})
        raise PaymentFailure({"code":"PAYMENT_REFERENCE_MISMATCH"})
    if data["status"] == "PAID":
        if data.get("amount_minor") is None or data.get("currency") is None:
            raise PaymentFailure({"code":"PAYMENT_AMOUNT_OR_CURRENCY_REQUIRED"})
        if data["amount_minor"] != payment.amount_minor or data["currency"] != payment.currency:
            log_action(actor=None, action="PAYMENT_WEBHOOK_AMOUNT_OR_CURRENCY_REJECTED", target=payment, after={"provider_event_id":data["event_id"],"provider_amount_minor":data["amount_minor"],"provider_currency":data["currency"]})
            raise PaymentFailure({"code":"PAYMENT_AMOUNT_OR_CURRENCY_MISMATCH"})
    result = confirm_payment(payment=payment, provider_event_id=data["event_id"], event_type=data["event_type"], normalized_status=data["status"], webhook_event=event, event_data=data)
    reconciliation = result["reconciliation"]
    event.processing_status = "LATE_PAYMENT_REQUIRES_RECONCILIATION" if reconciliation else "PROCESSED"
    event.processed_at = timezone.now()
    event.save(update_fields=["processing_status", "processed_at"])
    return {"duplicate": False, "payment_id": str(payment.id), "reconciliation_required": bool(reconciliation), "reconciliation_id": str(reconciliation.id) if reconciliation else None}


@transaction.atomic
def process_pesoway_webhook(*, raw_body, headers):
    """Reconcile a signed PesoWay event against its authoritative API record."""
    adapter = get_adapter("pesoway")
    event_data = adapter.verify_webhook(raw_body=raw_body, headers=headers)
    if not event_data:
        raise PaymentFailure({"code": "INVALID_WEBHOOK_SIGNATURE"})
    event, created = WebhookEvent.objects.get_or_create(
        provider_code="pesoway",
        provider_event_id=event_data["event_id"],
        defaults={"verified": True, "raw_body": raw_body.decode("utf-8")},
    )
    if not created:
        return {"duplicate": True}
    payment = Payment.objects.filter(provider_code="pesoway", provider_reference=event_data["provider_reference"]).first()
    if not payment:
        event.processing_status = "UNKNOWN_PAYMENT"
        event.processed_at = timezone.now()
        event.save(update_fields=["processing_status", "processed_at"])
        raise PaymentFailure({"code": "UNKNOWN_PAYMENT"})
    try:
        intent = adapter.retrieve_payment_intent(payment.provider_reference)
        provider_status = intent["status"]
        merchant_reference = intent["merchant_reference"]
        amount_minor = intent["amount_centavos"]
        currency = intent["currency"].upper()
    except (KeyError, TypeError, ValueError):
        raise PaymentFailure({"code": "PESOWAY_STATUS_LOOKUP_FAILED"})
    if str(intent.get("id")) != payment.provider_reference or merchant_reference != payment.provider_merchant_reference:
        raise PaymentFailure({"code": "PAYMENT_REFERENCE_MISMATCH"})
    if amount_minor != payment.amount_minor or currency != payment.currency:
        raise PaymentFailure({"code": "PAYMENT_AMOUNT_OR_CURRENCY_MISMATCH"})
    status_map = {"succeeded": "PAID", "canceled": "CANCELLED", "expired": "EXPIRED", "failed": "FAILED"}
    normalized_status = status_map.get(provider_status, "PENDING")
    payment.provider_status = provider_status
    payment.save(update_fields=["provider_status", "updated_at"])
    result = confirm_payment(
        payment=payment,
        provider_event_id=event_data["event_id"],
        event_type=event_data["event_type"],
        normalized_status=normalized_status,
        webhook_event=event,
        event_data={"amount_minor": amount_minor, "currency": currency, "merchant_reference": merchant_reference},
    )
    reconciliation = result["reconciliation"]
    event.processing_status = "LATE_PAYMENT_REQUIRES_RECONCILIATION" if reconciliation else "PROCESSED"
    event.processed_at = timezone.now()
    event.save(update_fields=["processing_status", "processed_at"])
    return {"duplicate": False, "payment_id": str(payment.id), "reconciliation_required": bool(reconciliation)}


def _require_superadmin(actor):
    if not actor or actor.primary_role != "SUPERADMIN" or actor.account_status != "ACTIVE":
        raise PermissionDenied("Superadmin access is required.")


def _create_reallocation_reservations(*, order):
    """Validate the original items against current sellability and allocate them under locks."""
    supplier_orders = _lock_supplier_orders(order)
    items = []
    for supplier_order in supplier_orders:
        items.extend(list(supplier_order.items.select_related("product__supplier").order_by("pk")))
    inventory_ids = [item.product_id for item in items if item.product_id]
    inventories = {inventory.product_id: inventory for inventory in Inventory.objects.select_for_update().select_related("product__supplier").filter(product_id__in=inventory_ids).order_by("pk")}
    if len(items) != len(inventories):
        raise PaymentFailure({"code": "REALLOCATION_PRODUCT_UNAVAILABLE"})
    required = {}
    for item in items:
        product = item.product
        inventory = inventories.get(product.id)
        if not inventory or not is_product_purchasable(product) or item.quantity < product.minimum_order_quantity:
            raise PaymentFailure({"code": "REALLOCATION_PRODUCT_UNAVAILABLE"})
        required[inventory.id] = required.get(inventory.id, 0) + item.quantity
    for inventory_id, quantity in required.items():
        if inventories_by_id := {inventory.id: inventory for inventory in inventories.values()}:
            if inventories_by_id[inventory_id].available_quantity < quantity:
                raise PaymentFailure({"code": "REALLOCATION_INSUFFICIENT_STOCK"})
    supplier_by_id = {supplier_order.id: supplier_order for supplier_order in supplier_orders}
    for item in items:
        inventory = inventories[item.product_id]
        inventory.available_quantity -= item.quantity
        inventory.reserved_quantity += item.quantity
        inventory.status = "ACTIVE" if inventory.available_quantity else "OUT_OF_STOCK"
        inventory.save(update_fields=["available_quantity", "reserved_quantity", "status", "updated_at"])
        reservation = InventoryReservation.objects.create(inventory=inventory, quantity=item.quantity, supplier_order=supplier_by_id[item.supplier_order_id], expires_at=timezone.now())
        InventoryMovement.objects.create(inventory=inventory, movement_type="RESERVATION", quantity_delta=-item.quantity, reason=f"Approved late-payment reallocation for {order.order_number}", actor=None, reference_type="orders.SupplierOrder", reference_id=reservation.supplier_order_id)


@transaction.atomic
def resolve_payment_reconciliation(*, reconciliation, actor, resolution, notes=""):
    """Perform a single, explicitly approved operational resolution for a late payment."""
    _require_superadmin(actor)
    reconciliation = PaymentReconciliation.objects.select_for_update().select_related("payment", "master_order").get(pk=reconciliation.pk)
    if reconciliation.status in {PaymentReconciliation.Status.REALLOCATED, PaymentReconciliation.Status.REFUND_REQUIRED}:
        return reconciliation
    order, payment = _lock_order(reconciliation.payment_id)
    if resolution == "INVESTIGATING":
        reconciliation.status = PaymentReconciliation.Status.INVESTIGATING
    elif resolution == "REFUND_REQUIRED":
        reconciliation.status = PaymentReconciliation.Status.REFUND_REQUIRED
    elif resolution == "REALLOCATE":
        _create_reallocation_reservations(order=order)
        _finalize_paid_payment(payment=payment, order=order)
        reconciliation.status = PaymentReconciliation.Status.REALLOCATED
    else:
        raise PaymentFailure({"code": "INVALID_RECONCILIATION_RESOLUTION"})
    reconciliation.resolution_notes = notes
    reconciliation.resolved_by = actor
    reconciliation.resolved_at = timezone.now() if resolution != "INVESTIGATING" else None
    reconciliation.save(update_fields=["status", "resolution_notes", "resolved_by", "resolved_at", "updated_at"])
    PaymentReconciliationHistory.objects.create(reconciliation=reconciliation, action=resolution, actor=actor, notes=notes)
    log_action(actor=actor, action=f"PAYMENT_RECONCILIATION_{resolution}", target=reconciliation, after={"status": reconciliation.status, "payment_id": str(payment.id), "order_id": str(order.id)})
    return reconciliation


def _refund_authorized(actor):
    _require_superadmin(actor)


def _refund_committed_statuses():
    return {"REQUESTED", "APPROVED", "PROCESSING", "COMPLETED"}


@transaction.atomic
def create_refund(*, payment, actor, allocations, idempotency_key, reason):
    """Create a superadmin-controlled request; it does not move money or wallet balances."""
    _refund_authorized(actor)
    order, payment = _lock_order(payment.pk)
    if payment.status not in {"PAID", "PARTIALLY_REFUNDED"} or not idempotency_key:
        raise PaymentFailure({"code": "PAYMENT_NOT_REFUNDABLE"})
    existing = Refund.objects.filter(payment=payment, idempotency_key=idempotency_key).first()
    if existing: return existing
    if not allocations: raise PaymentFailure({"code": "REFUND_ALLOCATIONS_REQUIRED"})
    supplier_orders = {x.id: x for x in _lock_supplier_orders(order)}
    amount = 0
    item_quantities, item_amounts, supplier_amounts = {}, {}, {}
    for allocation in allocations:
        supplier_order, item = allocation.get("supplier_order"), allocation.get("order_item")
        allocation_amount = allocation.get("amount_minor", 0)
        if allocation.get("currency", payment.currency) != payment.currency or allocation_amount <= 0:
            raise PaymentFailure({"code": "REFUND_AMOUNT_OR_CURRENCY_INVALID"})
        if not supplier_order or supplier_order.id not in supplier_orders:
            raise PaymentFailure({"code": "INVALID_REFUND_SUPPLIER_ORDER"})
        if item and item.supplier_order_id != supplier_order.id:
            raise PaymentFailure({"code": "INVALID_REFUND_ITEM"})
        if item and item.currency != payment.currency:
            raise PaymentFailure({"code": "REFUND_CURRENCY_MISMATCH"})
        quantity = allocation.get("quantity")
        if quantity is not None and (not item or quantity <= 0):
            raise PaymentFailure({"code": "INVALID_REFUND_QUANTITY"})
        amount += allocation_amount
        supplier_amounts[supplier_order.id] = supplier_amounts.get(supplier_order.id, 0) + allocation_amount
        if item:
            item_amounts[item.id] = item_amounts.get(item.id, 0) + allocation_amount
            item_quantities[item.id] = item_quantities.get(item.id, 0) + (quantity or 0)
    committed = payment.refunds.filter(status__in=_refund_committed_statuses()).aggregate(total=Sum("amount_minor"))["total"] or 0
    if amount <= 0 or committed + amount > payment.paid_minor:
        raise PaymentFailure({"code": "REFUND_AMOUNT_INVALID"})
    existing_allocations = RefundAllocation.objects.filter(refund__payment=payment, refund__status__in=_refund_committed_statuses()).select_related("refund")
    for supplier_id, requested in supplier_amounts.items():
        used = existing_allocations.filter(supplier_order_id=supplier_id).aggregate(total=Sum("amount_minor"))["total"] or 0
        if used + requested > supplier_orders[supplier_id].total_minor: raise PaymentFailure({"code": "SUPPLIER_REFUND_AMOUNT_EXCEEDED"})
    for item_id, requested in item_amounts.items():
        item = next(a["order_item"] for a in allocations if a.get("order_item") and a["order_item"].id == item_id)
        used = existing_allocations.filter(order_item_id=item_id).aggregate(total=Sum("amount_minor"))["total"] or 0
        used_quantity = existing_allocations.filter(order_item_id=item_id).aggregate(total=Sum("quantity"))["total"] or 0
        if used + requested > item.line_total_minor or used_quantity + item_quantities[item_id] > item.quantity: raise PaymentFailure({"code": "ITEM_REFUND_ALLOCATION_EXCEEDED"})
    refund_ref = hashlib.sha256(idempotency_key.encode()).hexdigest()[:10]
    refund = Refund.objects.create(payment=payment, reference=f"REF-{payment.id.hex[:12]}-{refund_ref}", amount_minor=amount, currency=payment.currency, reason=reason, idempotency_key=idempotency_key)
    for allocation in allocations:
        RefundAllocation.objects.create(refund=refund, supplier_order=allocation["supplier_order"], order_item=allocation.get("order_item"), quantity=allocation.get("quantity"), amount_minor=allocation["amount_minor"])
    log_action(actor=actor, action="REFUND_REQUESTED", target=refund, after={"amount_minor": amount, "currency": refund.currency})
    return refund


@transaction.atomic
def approve_refund(*, refund, actor, approve, reason=""):
    _refund_authorized(actor)
    refund = Refund.objects.select_for_update().get(pk=refund.pk)
    if refund.status != Refund.Status.REQUESTED: raise PaymentFailure({"code": "INVALID_REFUND_TRANSITION"})
    if approve:
        refund.status, refund.approved_by, refund.approved_at = Refund.Status.APPROVED, actor, timezone.now()
        fields=["status","approved_by","approved_at"]
        action="REFUND_APPROVED"
    else:
        if not reason: raise PaymentFailure({"code": "REFUND_REJECTION_REASON_REQUIRED"})
        refund.status, refund.rejected_by, refund.rejected_at, refund.rejection_reason = Refund.Status.REJECTED, actor, timezone.now(), reason
        fields=["status","rejected_by","rejected_at","rejection_reason"]
        action="REFUND_REJECTED"
    refund.save(update_fields=fields)
    if approve:
        from apps.notifications.services import emit
        emit("refund.approved",refund,{"recipient_ids":[str(refund.payment.master_order.customer.user_id)],"order_number":refund.payment.master_order.order_number,"link":f"/shop/orders/{refund.payment.master_order_id}/"})
    log_action(actor=actor, action=action, target=refund, after={"status":refund.status}); return refund


@transaction.atomic
def initiate_refund(*, refund, actor):
    _refund_authorized(actor)
    order, payment = _lock_order(refund.payment_id)
    refund = Refund.objects.select_for_update().get(pk=refund.pk)
    if refund.status == Refund.Status.PROCESSING: return refund
    if refund.status != Refund.Status.APPROVED: raise PaymentFailure({"code":"REFUND_NOT_APPROVED"})
    result = get_adapter(payment.provider_code).create_refund(refund=refund, idempotency_key=refund.idempotency_key)
    refund.provider_code=payment.provider_code;refund.provider_reference=result["provider_reference"];refund.provider_status=result["status"];refund.provider_response=result.get("response",{});refund.status=Refund.Status.PROCESSING;refund.initiated_at=timezone.now()
    refund.save(update_fields=["provider_code","provider_reference","provider_status","provider_response","status","initiated_at"])
    from apps.notifications.services import emit
    emit("refund.processing",refund,{"recipient_ids":[str(order.customer.user_id)],"order_number":order.order_number,"link":f"/shop/orders/{order.id}/"})
    log_action(actor=actor,action="REFUND_PROVIDER_INITIATED",target=refund,after={"provider_reference":refund.provider_reference,"status":refund.status})
    return refund


@transaction.atomic
def complete_refund(*, refund, provider_event_id, event_type, normalized_status, actor=None, payload_digest=""):
    """Apply verified provider completion exactly once; pending/failed events never affect totals."""
    order, payment = _lock_order(refund.payment_id)
    refund = Refund.objects.select_for_update().get(pk=refund.pk)
    event, created = RefundEvent.objects.get_or_create(provider_code=refund.provider_code, provider_event_id=provider_event_id, defaults={"refund":refund,"event_type":event_type,"normalized_status":normalized_status,"payload_digest":payload_digest})
    if not created: return refund
    if normalized_status == "COMPLETED":
        if refund.status == Refund.Status.COMPLETED:
            event.processed_at=timezone.now();event.save(update_fields=["processed_at"]);return refund
        if refund.status != Refund.Status.PROCESSING: raise PaymentFailure({"code":"REFUND_NOT_PROCESSING"})
        payment.refunded_minor += refund.amount_minor
        if payment.refunded_minor > payment.paid_minor: raise PaymentFailure({"code":"REFUND_AMOUNT_INVALID"})
        payment.status = Payment.Status.REFUNDED if payment.refunded_minor == payment.paid_minor else Payment.Status.PARTIALLY_REFUNDED
        payment.save(update_fields=["refunded_minor","status","updated_at"])
        refund.status=Refund.Status.COMPLETED;refund.provider_status="COMPLETED";refund.completed_at=timezone.now();refund.save(update_fields=["status","provider_status","completed_at"])
        from apps.wallets.services import reverse_refund
        reverse_refund(refund,actor=actor)
        from apps.notifications.services import emit
        emit("refund.completed",refund,{"recipient_ids":[str(order.customer.user_id)],"order_number":order.order_number,"link":f"/shop/orders/{order.id}/"})
        log_action(actor=actor,action="REFUND_COMPLETED",target=refund,after={"payment_refunded_minor":payment.refunded_minor,"payment_status":payment.status})
    elif normalized_status == "FAILED":
        if refund.status == Refund.Status.PROCESSING:
            refund.status=Refund.Status.FAILED;refund.provider_status="FAILED";refund.failed_at=timezone.now();refund.save(update_fields=["status","provider_status","failed_at"])
            from apps.notifications.services import emit
            emit("refund.failed",refund,{"recipient_ids":[str(order.customer.user_id)],"order_number":order.order_number,"link":f"/shop/orders/{order.id}/","priority":"HIGH"})
            log_action(actor=actor,action="REFUND_FAILED",target=refund,after={"status":refund.status})
    event.processed_at=timezone.now();event.save(update_fields=["processed_at"])
    return refund


@transaction.atomic
def process_refund_webhook(*, provider_code, raw_body, headers):
    data=get_adapter(provider_code).verify_refund_webhook(raw_body=raw_body,headers=headers)
    if not data: raise PaymentFailure({"code":"INVALID_REFUND_WEBHOOK_SIGNATURE"})
    refund=Refund.objects.filter(provider_code=provider_code,provider_reference=data["provider_reference"]).first()
    if not refund: raise PaymentFailure({"code":"UNKNOWN_REFUND"})
    if data.get("amount_minor") is not None and data["amount_minor"] != refund.amount_minor or data.get("currency") is not None and data["currency"] != refund.currency: raise PaymentFailure({"code":"REFUND_AMOUNT_OR_CURRENCY_INVALID"})
    digest=hashlib.sha256(raw_body).hexdigest()
    return complete_refund(refund=refund,provider_event_id=data["event_id"],event_type=data["event_type"],normalized_status=data["status"],payload_digest=digest)


def _cod_fulfillment_actor(actor, supplier):
    from apps.accounts.permissions import can_manage_fulfillment
    if not can_manage_fulfillment(actor, supplier): raise PermissionDenied("Supplier fulfillment access is required.")


@transaction.atomic
def select_cod(*, customer, order):
    order=MasterOrder.objects.select_for_update().get(pk=order.pk)
    if order.customer_id != customer.id: raise PaymentFailure({"code":"ORDER_ACCESS_DENIED"})
    existing=CODCommitment.objects.filter(master_order=order).first()
    if existing:
        if existing.status == CODCommitment.Status.ACTIVE:return existing
        raise PaymentFailure({"code":"COD_NOT_ELIGIBLE"})
    if order.status!="PENDING_PAYMENT" or order.payment_status!="PENDING" or not InventoryReservation.objects.filter(supplier_order__master_order=order,status="ACTIVE").exists(): raise PaymentFailure({"code":"COD_NOT_ELIGIBLE"})
    if Payment.objects.filter(master_order=order).exists(): raise PaymentFailure({"code":"ONLINE_PAYMENT_ALREADY_INITIATED"})
    commitment=CODCommitment.objects.create(master_order=order,selected_by=customer.user)
    order.status="COD_COMMITTED";order.payment_status="COD_PENDING";order.save(update_fields=["status","payment_status"])
    order.supplier_orders.update(status="PENDING_SUPPLIER")
    from apps.notifications.services import emit
    emit("cod.selected",commitment,{"recipient_ids":[str(customer.user_id)],"order_number":order.order_number,"link":f"/shop/orders/{order.id}/"})
    log_action(actor=customer.user,action="COD_SELECTED",target=commitment,after={"order_id":str(order.id)})
    return commitment


@transaction.atomic
def accept_cod_supplier_order(*, supplier_order, actor):
    supplier_order=SupplierOrder.objects.select_for_update().select_related("master_order","supplier").get(pk=supplier_order.pk);_cod_fulfillment_actor(actor,supplier_order.supplier)
    if not hasattr(supplier_order.master_order,"cod_commitment") or supplier_order.master_order.cod_commitment.status!="ACTIVE":raise PaymentFailure({"code":"COD_NOT_COMMITTED"})
    if supplier_order.status=="CONFIRMED":return supplier_order
    if supplier_order.status!="PENDING_SUPPLIER":raise PaymentFailure({"code":"INVALID_COD_TRANSITION"})
    supplier_order.status="CONFIRMED";supplier_order.save(update_fields=["status"])
    from apps.notifications.services import emit
    emit("cod.supplier_accepted",supplier_order,{"recipient_ids":[str(supplier_order.master_order.customer.user_id)],"order_number":supplier_order.master_order.order_number,"supplier_name":supplier_order.supplier_name_snapshot,"link":f"/shop/orders/{supplier_order.master_order_id}/"})
    log_action(actor=actor,action="COD_SUPPLIER_ACCEPTED",target=supplier_order);return supplier_order


@transaction.atomic
def record_cod_collection(*, supplier_order, actor, amount_minor, currency, collection_reference, evidence_metadata=None):
    supplier_order=SupplierOrder.objects.select_for_update().select_related("master_order","supplier").get(pk=supplier_order.pk);_cod_fulfillment_actor(actor,supplier_order.supplier)
    if supplier_order.status not in {"DELIVERED","COMPLETED"}:raise PaymentFailure({"code":"COD_COLLECTION_NOT_DELIVERED"})
    if amount_minor!=supplier_order.total_minor or currency!=supplier_order.currency or not collection_reference:raise PaymentFailure({"code":"COD_COLLECTION_AMOUNT_OR_CURRENCY_INVALID"})
    existing=CODCollection.objects.filter(supplier_order=supplier_order).first()
    if existing:return existing
    collection=CODCollection.objects.create(supplier_order=supplier_order,collected_by=actor,amount_minor=amount_minor,currency=currency,collection_reference=collection_reference,evidence_metadata=evidence_metadata or {})
    from apps.notifications.services import emit, supplier_recipient_ids
    payload={"order_number":supplier_order.master_order.order_number,"supplier_name":supplier_order.supplier_name_snapshot,"link":f"/shop/orders/{supplier_order.master_order_id}/"}
    emit("cod.collection_recorded",supplier_order,{"recipient_ids":[str(supplier_order.master_order.customer.user_id)],**payload})
    emit("cod.collection_recorded",supplier_order,{"recipient_ids":supplier_recipient_ids(supplier_order.supplier),**payload,"link":"/supplier/orders/"})
    log_action(actor=actor,action="COD_CASH_COLLECTED",target=collection,after={"supplier_order_id":str(supplier_order.id),"amount_minor":amount_minor})
    _complete_cod_if_confirmed(supplier_order);return collection


@transaction.atomic
def confirm_cod_receipt(*, supplier_order, customer):
    supplier_order=SupplierOrder.objects.select_for_update().select_related("master_order").get(pk=supplier_order.pk)
    if supplier_order.master_order.customer_id!=customer.id:raise PermissionDenied("Customer order access is required.")
    if supplier_order.status not in {"DELIVERED","COMPLETED"}:raise PaymentFailure({"code":"COD_RECEIPT_NOT_DELIVERED"})
    receipt,created=CODReceiptConfirmation.objects.get_or_create(supplier_order=supplier_order,defaults={"confirmed_by":customer.user})
    if created:
        from apps.notifications.services import emit, supplier_recipient_ids
        emit("cod.receipt_confirmed",supplier_order,{"recipient_ids":[str(customer.user_id)],"order_number":supplier_order.master_order.order_number,"link":f"/shop/orders/{supplier_order.master_order_id}/"})
        emit("cod.receipt_confirmed",supplier_order,{"recipient_ids":supplier_recipient_ids(supplier_order.supplier),"order_number":supplier_order.master_order.order_number,"link":"/supplier/orders/"})
        log_action(actor=customer.user,action="COD_RECEIPT_CONFIRMED",target=receipt,after={"supplier_order_id":str(supplier_order.id)})
    _complete_cod_if_confirmed(supplier_order);return receipt


def _complete_cod_if_confirmed(supplier_order):
    if not hasattr(supplier_order,"cod_collection") or not hasattr(supplier_order,"cod_receipt_confirmation"):return False
    if supplier_order.status=="COMPLETED":return True
    supplier_order.status="COMPLETED";supplier_order.save(update_fields=["status"])
    from apps.wallets.services import post_supplier_order_earnings
    post_supplier_order_earnings(supplier_order)
    _consume_cod_supplier_reservations(supplier_order)
    if not SupplierOrder.objects.filter(master_order=supplier_order.master_order).exclude(status__in=["COMPLETED","CANCELLED"]).exists():
        supplier_order.master_order.payment_status="COD_COLLECTED";supplier_order.master_order.save(update_fields=["payment_status"])
    log_action(actor=None,action="COD_SETTLEMENT_ELIGIBLE",target=supplier_order);return True


@transaction.atomic
def _consume_cod_supplier_reservations(supplier_order):
    """Consume one completed COD supplier order without affecting other suppliers' allocations."""
    order=MasterOrder.objects.select_for_update().get(pk=supplier_order.master_order_id)
    supplier_order=SupplierOrder.objects.select_for_update().get(pk=supplier_order.pk)
    reservations=list(InventoryReservation.objects.select_for_update().filter(supplier_order=supplier_order,status="ACTIVE").order_by("inventory_id","pk"))
    inventories={inventory.id:inventory for inventory in Inventory.objects.select_for_update().filter(id__in=[row.inventory_id for row in reservations]).order_by("pk")}
    for reservation in reservations:
        inventory=inventories[reservation.inventory_id]
        if inventory.reserved_quantity < reservation.quantity: raise PaymentFailure({"code":"RESERVATION_INCONSISTENT"})
        inventory.reserved_quantity-=reservation.quantity;inventory.sold_quantity+=reservation.quantity;inventory.save(update_fields=["reserved_quantity","sold_quantity","updated_at"])
        reservation.status="CONSUMED";reservation.save(update_fields=["status","updated_at"])
        InventoryMovement.objects.create(inventory=inventory,movement_type="SALE",quantity_delta=-reservation.quantity,reason=f"COD completed {order.order_number}",actor=None,reference_type="orders.SupplierOrder",reference_id=supplier_order.id)


@transaction.atomic
def cancel_cod_before_acceptance(*, order, actor, reason):
    order=MasterOrder.objects.select_for_update().get(pk=order.pk)
    if not hasattr(actor,"customer_profile") or order.customer_id != actor.customer_profile.id: raise PermissionDenied("Customer order access is required.")
    commitment=CODCommitment.objects.select_for_update().get(master_order=order)
    if commitment.status!="ACTIVE" or order.supplier_orders.exclude(status="PENDING_SUPPLIER").exists():raise PaymentFailure({"code":"COD_CANCELLATION_NOT_ELIGIBLE"})
    release_reservations(master_order=order,actor=actor,expired=False);commitment.status="CANCELLED";commitment.cancelled_by=actor;commitment.cancelled_at=timezone.now();commitment.cancellation_reason=reason;commitment.save(update_fields=["status","cancelled_by","cancelled_at","cancellation_reason"])
    supplier_orders=list(order.supplier_orders.select_related("supplier"))
    order.status="CANCELLED";order.payment_status="CANCELLED";order.save(update_fields=["status","payment_status"]);order.supplier_orders.update(status="CANCELLED")
    from apps.notifications.services import emit, supplier_recipient_ids
    for supplier_order in supplier_orders:
        emit("cod.cancelled",supplier_order,{"recipient_ids":supplier_recipient_ids(supplier_order.supplier),"order_number":order.order_number,"link":"/supplier/orders/"})
    log_action(actor=actor,action="COD_CANCELLED",target=commitment);return commitment


@transaction.atomic
def report_cod_delivery_exception(*, supplier_order, actor, status, reason):
    supplier_order=SupplierOrder.objects.select_for_update().select_related("supplier").get(pk=supplier_order.pk);_cod_fulfillment_actor(actor,supplier_order.supplier)
    if status not in {CODException.Status.FAILED_DELIVERY,CODException.Status.DISPUTED} or not reason: raise PaymentFailure({"code":"INVALID_COD_EXCEPTION"})
    exception=CODException.objects.create(supplier_order=supplier_order,status=status,reason=reason,reported_by=actor)
    from apps.notifications.services import emit, superadmin_recipient_ids
    event_type="cod.failed_delivery" if status==CODException.Status.FAILED_DELIVERY else "cod.collection_disputed"
    emit(event_type,supplier_order,{"recipient_ids":superadmin_recipient_ids(),"order_number":supplier_order.master_order.order_number,"link":f"/operations/cod/orders/{supplier_order.id}/","priority":"HIGH"})
    log_action(actor=actor,action=f"COD_{status}",target=exception);return exception


@transaction.atomic
def verify_cod_return(*, exception, actor):
    _require_superadmin(actor)
    exception=CODException.objects.select_for_update().select_related("supplier_order").get(pk=exception.pk)
    if exception.status != CODException.Status.FAILED_DELIVERY: raise PaymentFailure({"code":"COD_RETURN_NOT_ELIGIBLE"})
    from apps.orders.services import release_reservation
    for reservation in exception.supplier_order.inventory_reservations.filter(status="ACTIVE").order_by("pk"):
        release_reservation(reservation=reservation,actor=actor,reason="Verified COD returned stock")
    exception.status=CODException.Status.RETURN_VERIFIED;exception.resolved_at=timezone.now();exception.save(update_fields=["status","resolved_at"])
    from apps.notifications.services import emit, supplier_recipient_ids
    emit("cod.return_verified",exception.supplier_order,{"recipient_ids":supplier_recipient_ids(exception.supplier_order.supplier),"order_number":exception.supplier_order.master_order.order_number,"link":"/supplier/orders/"})
    log_action(actor=actor,action="COD_RETURN_VERIFIED",target=exception);return exception


@transaction.atomic
def cancel_cod_supplier_order_before_acceptance(*, supplier_order, actor, reason):
    supplier_order=SupplierOrder.objects.select_for_update().select_related("master_order","supplier").get(pk=supplier_order.pk);_cod_fulfillment_actor(actor,supplier_order.supplier)
    if supplier_order.status!="PENDING_SUPPLIER" or not reason: raise PaymentFailure({"code":"COD_CANCELLATION_NOT_ELIGIBLE"})
    from apps.orders.services import release_reservation
    for reservation in supplier_order.inventory_reservations.filter(status="ACTIVE").order_by("pk"):
        release_reservation(reservation=reservation,actor=actor,reason="COD supplier cancellation before acceptance")
    supplier_order.status="CANCELLED";supplier_order.save(update_fields=["status"]);log_action(actor=actor,action="COD_SUPPLIER_ORDER_CANCELLED",target=supplier_order,after={"reason":reason});return supplier_order
