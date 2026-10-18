import hashlib
import uuid
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from apps.audit.services import log_action
from apps.inventory.models import Inventory, InventoryMovement, InventoryReservation
from apps.orders.models import MasterOrder
from .adapters import get_adapter
from .models import Payment, PaymentAttempt, PaymentEvent, Refund, RefundAllocation, WebhookEvent
class PaymentFailure(ValidationError): pass
@transaction.atomic
def initiate_payment(*, customer, order, provider_code, method_category, idempotency_key):
    if not idempotency_key:raise PaymentFailure({"code":"IDEMPOTENCY_REQUIRED"})
    order=MasterOrder.objects.select_for_update().get(pk=order.pk)
    if order.customer_id!=customer.id:raise PaymentFailure({"code":"ORDER_ACCESS_DENIED"})
    if order.payment_status=="PAID":raise PaymentFailure({"code":"ORDER_ALREADY_PAID"})
    payment=Payment.objects.filter(master_order=order,status__in=["PENDING","AUTHORIZED"]).first()
    if not payment:
        payment=Payment.objects.create(master_order=order,internal_reference=f"PAY-{order.order_number}-{uuid.uuid4().hex[:10]}",provider_code=provider_code,method_category=method_category,amount_minor=order.total_minor,currency=order.currency)
    if payment.provider_code!=provider_code:raise PaymentFailure({"code":"PAYMENT_PROVIDER_MISMATCH"})
    old=payment.attempts.filter(idempotency_key=idempotency_key).first()
    if old:return {"payment_id":str(payment.id),"attempt_id":old.id,"status":payment.status,"idempotent":True}
    adapter=get_adapter(provider_code);result=adapter.create_payment(payment=payment,idempotency_key=idempotency_key);payment.provider_reference=result["provider_reference"];payment.save(update_fields=["provider_reference","updated_at"])
    attempt=PaymentAttempt.objects.create(payment=payment,provider_code=provider_code,provider_attempt_reference=result["attempt_reference"],idempotency_key=idempotency_key,method_category=method_category,status=result["status"])
    return {"payment_id":str(payment.id),"attempt_id":attempt.id,"status":payment.status,"instruction_url":result["instruction_url"]}
@transaction.atomic
def consume_reservations(*, master_order, actor=None):
    reservations=list(InventoryReservation.objects.select_for_update().select_related("inventory").filter(supplier_order__master_order=master_order,status="ACTIVE").order_by("inventory__product_id"))
    if not reservations: raise PaymentFailure({"code":"NO_ACTIVE_RESERVATIONS"})
    inventory_ids=[r.inventory_id for r in reservations];inventories={x.id:x for x in Inventory.objects.select_for_update().filter(id__in=inventory_ids).order_by("product_id")}
    for reservation in reservations:
        inv=inventories[reservation.inventory_id]
        if inv.reserved_quantity<reservation.quantity:raise PaymentFailure({"code":"RESERVATION_INCONSISTENT"})
        inv.reserved_quantity-=reservation.quantity;inv.sold_quantity+=reservation.quantity;inv.save(update_fields=["reserved_quantity","sold_quantity","updated_at"])
        reservation.status="CONSUMED";reservation.save(update_fields=["status","updated_at"])
        InventoryMovement.objects.create(inventory=inv,movement_type="SALE",quantity_delta=-reservation.quantity,reason=f"Payment for {master_order.order_number}",actor=actor,reference_type="orders.SupplierOrder",reference_id=reservation.supplier_order_id)
@transaction.atomic
def release_reservations(*, master_order, actor=None, expired=False):
    reservations=list(InventoryReservation.objects.select_for_update().select_related("inventory").filter(supplier_order__master_order=master_order,status="ACTIVE").order_by("inventory__product_id"))
    for reservation in reservations:
        inv=Inventory.objects.select_for_update().get(pk=reservation.inventory_id);inv.available_quantity+=reservation.quantity;inv.reserved_quantity-=reservation.quantity;inv.status="ACTIVE";inv.save(update_fields=["available_quantity","reserved_quantity","status","updated_at"])
        reservation.status="EXPIRED" if expired else "RELEASED";reservation.save(update_fields=["status","updated_at"]);InventoryMovement.objects.create(inventory=inv,movement_type="RESERVATION_RELEASE",quantity_delta=reservation.quantity,reason="Payment reservation released",actor=actor,reference_type="orders.SupplierOrder",reference_id=reservation.supplier_order_id)
@transaction.atomic
def confirm_payment(*, payment, provider_event_id, event_type, normalized_status, webhook_event=None):
    payment=Payment.objects.select_for_update().select_related("master_order").get(pk=payment.pk)
    if PaymentEvent.objects.filter(payment=payment,provider_event_id=provider_event_id).exists():return payment
    digest=hashlib.sha256((provider_event_id+normalized_status).encode()).hexdigest()
    PaymentEvent.objects.create(payment=payment,webhook_event=webhook_event,provider_event_id=provider_event_id,event_type=event_type,normalized_status=normalized_status,payload_digest=digest)
    if normalized_status=="PAID":
        if payment.status=="PAID":return payment
        if payment.amount_minor!=payment.master_order.total_minor:raise PaymentFailure({"code":"PAYMENT_AMOUNT_MISMATCH"})
        consume_reservations(master_order=payment.master_order)
        payment.status="PAID";payment.paid_minor=payment.amount_minor;payment.paid_at=timezone.now();payment.save(update_fields=["status","paid_minor","paid_at","updated_at"])
        order=payment.master_order;order.payment_status="PAID";order.status="PROCESSING";order.save(update_fields=["payment_status","status"])
        for so in order.supplier_orders.select_for_update(): so.status="PENDING_SUPPLIER";so.save(update_fields=["status"])
        from apps.wallets.services import post_payment_earnings
        post_payment_earnings(order)
        from apps.notifications.services import emit
        emit("payment.succeeded",payment,{"recipient_ids":[str(order.customer.user_id)],"order_number":order.order_number,"link":f"/shop/payments/{payment.id}/"})
        log_action(actor=None,action="PAYMENT_CONFIRMED",target=payment,after={"status":"PAID"})
    elif normalized_status=="FAILED" and payment.status!="PAID":
        release_reservations(master_order=payment.master_order, expired=True)
        payment.status="FAILED";payment.save(update_fields=["status","updated_at"])
        order=payment.master_order;order.payment_status="FAILED";order.status="CANCELLED";order.save(update_fields=["payment_status","status"])
        order.supplier_orders.exclude(status="CANCELLED").update(status="CANCELLED")
        log_action(actor=None,action="PAYMENT_FAILED_ORDER_CANCELLED",target=payment,after={"status":"FAILED","order_status":"CANCELLED"})
    return payment
@transaction.atomic
def process_webhook(*, provider_code, raw_body, headers):
    adapter=get_adapter(provider_code);data=adapter.verify_webhook(raw_body=raw_body,headers=headers)
    if not data:raise PaymentFailure({"code":"INVALID_WEBHOOK_SIGNATURE"})
    event,created=WebhookEvent.objects.get_or_create(provider_code=provider_code,provider_event_id=data["event_id"],defaults={"verified":True,"raw_body":raw_body.decode()})
    if not created:return {"duplicate":True}
    payment=Payment.objects.filter(provider_code=provider_code,provider_reference=data["provider_reference"]).first()
    if not payment:event.processing_status="UNKNOWN_PAYMENT";event.save(update_fields=["processing_status"]);raise PaymentFailure({"code":"UNKNOWN_PAYMENT"})
    confirm_payment(payment=payment,provider_event_id=data["event_id"],event_type=data["event_type"],normalized_status=data["status"],webhook_event=event);event.processing_status="PROCESSED";event.processed_at=timezone.now();event.save(update_fields=["processing_status","processed_at"]);return {"duplicate":False,"payment_id":str(payment.id)}
@transaction.atomic
def create_refund(*, payment, actor, allocations, idempotency_key, reason):
    payment=Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status not in {"PAID","PARTIALLY_REFUNDED"}:raise PaymentFailure({"code":"PAYMENT_NOT_REFUNDABLE"})
    existing=Refund.objects.filter(payment=payment,idempotency_key=idempotency_key).first()
    if existing:return existing
    amount=sum(a["amount_minor"] for a in allocations)
    committed=payment.refunds.exclude(status="CANCELLED").aggregate(total=Sum("amount_minor"))["total"] or 0
    if amount<=0 or committed+amount>payment.paid_minor:raise PaymentFailure({"code":"REFUND_AMOUNT_INVALID"})
    refund_ref=hashlib.sha256(idempotency_key.encode()).hexdigest()[:10]
    refund=Refund.objects.create(payment=payment,reference=f"REF-{payment.id.hex[:12]}-{refund_ref}",amount_minor=amount,currency=payment.currency,reason=reason,idempotency_key=idempotency_key)
    for allocation in allocations:
        so=allocation["supplier_order"];item=allocation.get("order_item")
        if so.master_order_id!=payment.master_order_id or item and item.supplier_order_id!=so.id:raise PaymentFailure({"code":"INVALID_REFUND_ALLOCATION"})
        RefundAllocation.objects.create(refund=refund,supplier_order=so,order_item=item,quantity=allocation.get("quantity"),amount_minor=allocation["amount_minor"])
    log_action(actor=actor,action="REFUND_CREATED",target=refund,after={"amount_minor":amount});return refund
