import uuid
from django.conf import settings
from django.db import models
class AuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="audit_events")
    action, target_type = models.CharField(max_length=80), models.CharField(max_length=120)
    target_id = models.UUIDField(null=True, blank=True)
    before, after = models.JSONField(default=dict), models.JSONField(default=dict)
    request_id = models.CharField(max_length=128, blank=True); created_at = models.DateTimeField(auto_now_add=True)
    class Meta: indexes = [models.Index(fields=["target_type", "target_id", "created_at"]), models.Index(fields=["actor", "created_at"])]
