import uuid
from django.conf import settings
from django.db import models
from apps.orders.models import MasterOrder, SupplierOrder, OrderItem
class Payment(models.Model):
    class Status(models.TextChoices): PENDING="PENDING","Pending"; AUTHORIZED="AUTHORIZED","Authorized"; PAID="PAID","Paid"; FAILED="FAILED","Failed"; CANCELLED="CANCELLED","Cancelled"; EXPIRED="EXPIRED","Expired"; PARTIALLY_REFUNDED="PARTIALLY_REFUNDED","Partially refunded"; REFUNDED="REFUNDED","Refunded"
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False); master_order=models.ForeignKey(MasterOrder,on_delete=models.PROTECT,related_name="payments"); internal_reference=models.CharField(max_length=64,unique=True); provider_code=models.CharField(max_length=40); provider_reference=models.CharField(max_length=160,blank=True); provider_merchant_reference=models.CharField(max_length=160,blank=True); provider_status=models.CharField(max_length=32,blank=True); method_category=models.CharField(max_length=32); amount_minor=models.PositiveBigIntegerField(); paid_minor=models.PositiveBigIntegerField(default=0); refunded_minor=models.PositiveBigIntegerField(default=0); currency=models.CharField(max_length=3); status=models.CharField(max_length=24,choices=Status.choices,default=Status.PENDING); created_at=models.DateTimeField(auto_now_add=True); paid_at=models.DateTimeField(null=True,blank=True);updated_at=models.DateTimeField(auto_now=True)
    class Meta: constraints=[models.UniqueConstraint(fields=["provider_code","provider_reference"],condition=~models.Q(provider_reference=""),name="unique_provider_payment_reference"),models.UniqueConstraint(fields=["provider_code","provider_merchant_reference"],condition=~models.Q(provider_merchant_reference=""),name="unique_provider_merchant_reference")]
class PaymentAttempt(models.Model):
    payment=models.ForeignKey(Payment,on_delete=models.PROTECT,related_name="attempts"); provider_code=models.CharField(max_length=40); provider_attempt_reference=models.CharField(max_length=160,unique=True); idempotency_key=models.CharField(max_length=128); method_category=models.CharField(max_length=32); status=models.CharField(max_length=24,default="PENDING"); failure_code=models.CharField(max_length=64,blank=True); failure_message=models.CharField(max_length=255,blank=True); created_at=models.DateTimeField(auto_now_add=True); completed_at=models.DateTimeField(null=True,blank=True)
    class Meta: constraints=[models.UniqueConstraint(fields=["payment","idempotency_key"],name="unique_payment_attempt_key"),models.UniqueConstraint(fields=["payment"],condition=models.Q(status="PENDING"),name="one_pending_attempt_per_payment")]
class WebhookEvent(models.Model):
    provider_code=models.CharField(max_length=40); provider_event_id=models.CharField(max_length=160); verified=models.BooleanField(default=False); raw_body=models.TextField(); received_at=models.DateTimeField(auto_now_add=True); processed_at=models.DateTimeField(null=True,blank=True); processing_status=models.CharField(max_length=24,default="RECEIVED")
    class Meta: constraints=[models.UniqueConstraint(fields=["provider_code","provider_event_id"],name="unique_webhook_event")]
class PaymentEvent(models.Model):
    payment=models.ForeignKey(Payment,on_delete=models.PROTECT,related_name="events"); webhook_event=models.OneToOneField(WebhookEvent,on_delete=models.PROTECT,null=True,blank=True); provider_event_id=models.CharField(max_length=160); event_type=models.CharField(max_length=64); normalized_status=models.CharField(max_length=24); payload_digest=models.CharField(max_length=64); processed_at=models.DateTimeField(auto_now_add=True)
    class Meta: constraints=[models.UniqueConstraint(fields=["payment","provider_event_id"],name="unique_payment_event")]
class PaymentReconciliation(models.Model):
    """A durable operations record for a verified payment that cannot be fulfilled safely."""
    class Status(models.TextChoices):
        OPEN="OPEN","Open"
        INVESTIGATING="INVESTIGATING","Investigating"
        REALLOCATED="REALLOCATED","Reallocated"
        REFUND_REQUIRED="REFUND_REQUIRED","Refund required"

    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    payment=models.ForeignKey(Payment,on_delete=models.PROTECT,related_name="reconciliations")
    master_order=models.ForeignKey(MasterOrder,on_delete=models.PROTECT,related_name="payment_reconciliations")
    webhook_event=models.OneToOneField(WebhookEvent,on_delete=models.PROTECT,related_name="reconciliation")
    provider_code=models.CharField(max_length=40)
    provider_event_id=models.CharField(max_length=160)
    reason_code=models.CharField(max_length=64,default="LATE_PAYMENT_REQUIRES_RECONCILIATION")
    amount_minor=models.PositiveBigIntegerField()
    currency=models.CharField(max_length=3)
    provider_amount_minor=models.PositiveBigIntegerField(null=True,blank=True)
    provider_currency=models.CharField(max_length=3,blank=True)
    provider_event_at=models.DateTimeField(null=True,blank=True)
    status=models.CharField(max_length=24,choices=Status.choices,default=Status.OPEN)
    resolution_notes=models.TextField(blank=True)
    resolved_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.PROTECT,related_name="resolved_payment_reconciliations")
    resolved_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["provider_code","provider_event_id"],name="unique_reconciliation_provider_event")]
        indexes=[models.Index(fields=["status","created_at"]),models.Index(fields=["master_order","status"])]

class PaymentReconciliationHistory(models.Model):
    reconciliation=models.ForeignKey(PaymentReconciliation,on_delete=models.PROTECT,related_name="history")
    action=models.CharField(max_length=48)
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.PROTECT)
    notes=models.TextField(blank=True)
    metadata=models.JSONField(default=dict)
    created_at=models.DateTimeField(auto_now_add=True)
class Refund(models.Model):
    class Status(models.TextChoices): REQUESTED="REQUESTED","Requested"; APPROVED="APPROVED","Approved"; REJECTED="REJECTED","Rejected"; PROCESSING="PROCESSING","Processing"; COMPLETED="COMPLETED","Completed"; FAILED="FAILED","Failed"; CANCELLED="CANCELLED","Cancelled"
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False); payment=models.ForeignKey(Payment,on_delete=models.PROTECT,related_name="refunds"); reference=models.CharField(max_length=64,unique=True); amount_minor=models.PositiveBigIntegerField();currency=models.CharField(max_length=3);reason=models.CharField(max_length=500);status=models.CharField(max_length=16,choices=Status.choices,default=Status.REQUESTED);idempotency_key=models.CharField(max_length=128);created_at=models.DateTimeField(auto_now_add=True)
    approved_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.PROTECT,related_name="approved_refunds"); approved_at=models.DateTimeField(null=True,blank=True); rejected_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.PROTECT,related_name="rejected_refunds"); rejected_at=models.DateTimeField(null=True,blank=True); rejection_reason=models.CharField(max_length=500,blank=True)
    provider_code=models.CharField(max_length=40,blank=True); provider_reference=models.CharField(max_length=160,blank=True); provider_status=models.CharField(max_length=24,blank=True); provider_response=models.JSONField(default=dict); initiated_at=models.DateTimeField(null=True,blank=True); completed_at=models.DateTimeField(null=True,blank=True); failed_at=models.DateTimeField(null=True,blank=True)
    class Meta: constraints=[models.UniqueConstraint(fields=["payment","idempotency_key"],name="unique_refund_key")]
class RefundAllocation(models.Model):
    refund=models.ForeignKey(Refund,on_delete=models.PROTECT,related_name="allocations");supplier_order=models.ForeignKey(SupplierOrder,on_delete=models.PROTECT);order_item=models.ForeignKey(OrderItem,on_delete=models.PROTECT,null=True,blank=True);quantity=models.PositiveIntegerField(null=True,blank=True);amount_minor=models.PositiveBigIntegerField()
class RefundEvent(models.Model):
    refund=models.ForeignKey(Refund,on_delete=models.PROTECT,related_name="events");provider_code=models.CharField(max_length=40);provider_event_id=models.CharField(max_length=160);event_type=models.CharField(max_length=64);normalized_status=models.CharField(max_length=24);payload_digest=models.CharField(max_length=64);received_at=models.DateTimeField(auto_now_add=True);processed_at=models.DateTimeField(null=True,blank=True)
    class Meta: constraints=[models.UniqueConstraint(fields=["provider_code","provider_event_id"],name="unique_refund_provider_event")]
class RefundWalletReversal(models.Model):
    class Status(models.TextChoices): APPLIED="APPLIED","Applied"; HELD="HELD","Held"
    refund_allocation=models.OneToOneField(RefundAllocation,on_delete=models.PROTECT,related_name="wallet_reversal");wallet=models.ForeignKey("wallets.Wallet",null=True,blank=True,on_delete=models.PROTECT,related_name="refund_reversals");amount_minor=models.PositiveBigIntegerField();currency=models.CharField(max_length=3);bucket=models.CharField(max_length=12,blank=True);status=models.CharField(max_length=12,choices=Status.choices);reason=models.CharField(max_length=500,blank=True);ledger_reference=models.CharField(max_length=160,blank=True);created_at=models.DateTimeField(auto_now_add=True);updated_at=models.DateTimeField(auto_now=True)
class CODCommitment(models.Model):
    class Status(models.TextChoices): ACTIVE="ACTIVE","Active"; CANCELLED="CANCELLED","Cancelled"; HELD="HELD","Held"
    master_order=models.OneToOneField(MasterOrder,on_delete=models.PROTECT,related_name="cod_commitment");selected_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="cod_commitments");status=models.CharField(max_length=16,choices=Status.choices,default=Status.ACTIVE);selected_at=models.DateTimeField(auto_now_add=True);cancelled_at=models.DateTimeField(null=True,blank=True);cancelled_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.PROTECT,related_name="cancelled_cod_commitments");cancellation_reason=models.CharField(max_length=500,blank=True)
class CODCollection(models.Model):
    supplier_order=models.OneToOneField(SupplierOrder,on_delete=models.PROTECT,related_name="cod_collection");collected_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="cod_collections");amount_minor=models.PositiveBigIntegerField();currency=models.CharField(max_length=3);collection_reference=models.CharField(max_length=160);evidence_metadata=models.JSONField(default=dict);collected_at=models.DateTimeField(auto_now_add=True)
    class Meta: constraints=[models.UniqueConstraint(fields=["supplier_order","collection_reference"],name="unique_cod_collection_reference")]
class CODReceiptConfirmation(models.Model):
    supplier_order=models.OneToOneField(SupplierOrder,on_delete=models.PROTECT,related_name="cod_receipt_confirmation");confirmed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="cod_receipt_confirmations");confirmed_at=models.DateTimeField(auto_now_add=True)
class CODException(models.Model):
    class Status(models.TextChoices): FAILED_DELIVERY="FAILED_DELIVERY","Failed delivery"; DISPUTED="DISPUTED","Disputed"; RETURN_VERIFIED="RETURN_VERIFIED","Return verified"
    supplier_order=models.ForeignKey(SupplierOrder,on_delete=models.PROTECT,related_name="cod_exceptions");status=models.CharField(max_length=24,choices=Status.choices);reason=models.CharField(max_length=500);reported_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT);created_at=models.DateTimeField(auto_now_add=True);resolved_at=models.DateTimeField(null=True,blank=True)
