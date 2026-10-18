from django.conf import settings
from django.db import models
class BusinessConfiguration(models.Model):
    key=models.CharField(max_length=80);version=models.CharField(max_length=40);value=models.JSONField();is_active=models.BooleanField(default=False);effective_from=models.DateTimeField();effective_to=models.DateTimeField(null=True,blank=True);updated_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT);created_at=models.DateTimeField(auto_now_add=True)
    class Meta:constraints=[models.UniqueConstraint(fields=["key","version"],name="unique_configuration_version")]
