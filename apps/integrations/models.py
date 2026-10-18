import uuid
from django.db import models
class ExternalSystem(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False);name=models.CharField(max_length=160);code=models.SlugField(unique=True);status=models.CharField(max_length=16,default="ACTIVE");allowed_scopes=models.JSONField(default=list);created_at=models.DateTimeField(auto_now_add=True);updated_at=models.DateTimeField(auto_now=True)
class IntegrationCredential(models.Model):
    system=models.ForeignKey(ExternalSystem,on_delete=models.PROTECT,related_name="credentials");key_id=models.UUIDField(default=uuid.uuid4,unique=True);secret_hash=models.CharField(max_length=128);scopes=models.JSONField(default=list);expires_at=models.DateTimeField(null=True,blank=True);revoked_at=models.DateTimeField(null=True,blank=True);created_at=models.DateTimeField(auto_now_add=True)
class ExternalIdentity(models.Model):
    system=models.ForeignKey(ExternalSystem,on_delete=models.PROTECT);local_type=models.CharField(max_length=120);local_id=models.UUIDField();external_id=models.CharField(max_length=160);status=models.CharField(max_length=16,default="ACTIVE")
    class Meta:constraints=[models.UniqueConstraint(fields=["system","external_id"],name="unique_external_identity")]
class ExternalReference(models.Model):
    system=models.ForeignKey(ExternalSystem,on_delete=models.PROTECT);local_type=models.CharField(max_length=120);local_id=models.UUIDField();external_reference=models.CharField(max_length=160);created_at=models.DateTimeField(auto_now_add=True)
    class Meta:constraints=[models.UniqueConstraint(fields=["system","local_type","local_id","external_reference"],name="unique_external_reference")]
class WebhookSubscription(models.Model):
    system=models.ForeignKey(ExternalSystem,on_delete=models.PROTECT);callback_url=models.URLField();event_types=models.JSONField(default=list);secret_hash=models.CharField(max_length=128);is_active=models.BooleanField(default=True)
class WebhookDelivery(models.Model):
    subscription=models.ForeignKey(WebhookSubscription,on_delete=models.PROTECT,related_name="deliveries");event_id=models.UUIDField();event_type=models.CharField(max_length=80);status=models.CharField(max_length=16,default="PENDING");attempt_count=models.PositiveIntegerField(default=0);response_status=models.PositiveIntegerField(null=True,blank=True);last_error=models.CharField(max_length=500,blank=True);created_at=models.DateTimeField(auto_now_add=True);last_attempted_at=models.DateTimeField(null=True,blank=True)
    class Meta:constraints=[models.UniqueConstraint(fields=["subscription","event_id"],name="unique_webhook_delivery")]
