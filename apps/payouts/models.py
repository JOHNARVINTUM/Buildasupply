import uuid
from django.conf import settings
from django.db import models
from apps.wallets.models import Wallet
class PayoutMethod(models.Model):
    wallet=models.ForeignKey(Wallet,on_delete=models.PROTECT,related_name="payout_methods");method_type=models.CharField(max_length=24);masked_destination=models.CharField(max_length=120);token_reference=models.CharField(max_length=255);is_active=models.BooleanField(default=True);is_preferred=models.BooleanField(default=False)
class PayoutRequest(models.Model):
    class Status(models.TextChoices): REQUESTED="REQUESTED","Requested";APPROVED="APPROVED","Approved";PROCESSING="PROCESSING","Processing";COMPLETED="COMPLETED","Completed";FAILED="FAILED","Failed";REJECTED="REJECTED","Rejected";CANCELLED="CANCELLED","Cancelled"
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False);wallet=models.ForeignKey(Wallet,on_delete=models.PROTECT,related_name="payouts");method=models.ForeignKey(PayoutMethod,on_delete=models.PROTECT);amount_minor=models.PositiveBigIntegerField();currency=models.CharField(max_length=3);status=models.CharField(max_length=16,choices=Status.choices,default=Status.REQUESTED);idempotency_key=models.CharField(max_length=128);requester=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="payout_requests");reviewer=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.PROTECT,related_name="reviewed_payouts");reason=models.CharField(max_length=500,blank=True);created_at=models.DateTimeField(auto_now_add=True);updated_at=models.DateTimeField(auto_now=True)
    class Meta:constraints=[models.UniqueConstraint(fields=["wallet","idempotency_key"],name="unique_payout_request_key")]
class PayoutTransaction(models.Model):
    payout=models.OneToOneField(PayoutRequest,on_delete=models.PROTECT,related_name="transaction");provider_code=models.CharField(max_length=40);provider_reference=models.CharField(max_length=160,unique=True);status=models.CharField(max_length=16);created_at=models.DateTimeField(auto_now_add=True)
