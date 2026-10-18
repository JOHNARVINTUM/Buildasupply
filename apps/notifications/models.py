import uuid
from django.conf import settings
from django.db import models
class DomainEvent(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False);event_type=models.CharField(max_length=80);object_type=models.CharField(max_length=120);object_id=models.UUIDField(null=True,blank=True);payload=models.JSONField(default=dict);status=models.CharField(max_length=16,default="PENDING");retry_count=models.PositiveIntegerField(default=0);last_error=models.CharField(max_length=500,blank=True);created_at=models.DateTimeField(auto_now_add=True);processed_at=models.DateTimeField(null=True,blank=True)
class Notification(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False);recipient=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="notifications");event=models.ForeignKey(DomainEvent,on_delete=models.PROTECT,related_name="notifications");event_type=models.CharField(max_length=80);title=models.CharField(max_length=160);body=models.TextField();priority=models.CharField(max_length=12,default="NORMAL");related_type=models.CharField(max_length=120);related_id=models.UUIDField(null=True,blank=True);link=models.CharField(max_length=255,blank=True);read_at=models.DateTimeField(null=True,blank=True);created_at=models.DateTimeField(auto_now_add=True)
    class Meta:constraints=[models.UniqueConstraint(fields=["recipient","event"],name="one_notification_per_recipient_event")];indexes=[models.Index(fields=["recipient","read_at","created_at"])]
class NotificationPreference(models.Model):
    recipient=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="notification_preferences");category=models.CharField(max_length=40);in_app=models.BooleanField(default=True);email=models.BooleanField(default=False)
    class Meta:constraints=[models.UniqueConstraint(fields=["recipient","category"],name="one_preference_category")]
class NotificationDelivery(models.Model):
    notification=models.ForeignKey(Notification,on_delete=models.PROTECT,related_name="deliveries");channel=models.CharField(max_length=16);status=models.CharField(max_length=16,default="PENDING");attempt_count=models.PositiveIntegerField(default=0);last_error=models.CharField(max_length=500,blank=True);created_at=models.DateTimeField(auto_now_add=True);sent_at=models.DateTimeField(null=True,blank=True)
