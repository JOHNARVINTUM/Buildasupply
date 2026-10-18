from django.db import models
from django.db.models import Q
from apps.customers.models import CustomerProfile
class MembershipTier(models.Model):
    code = models.SlugField(unique=True); name = models.CharField(max_length=80); is_active = models.BooleanField(default=True); description = models.TextField(blank=True)
    def __str__(self): return self.name
class MembershipBenefit(models.Model):
    tier = models.ForeignKey(MembershipTier, on_delete=models.PROTECT, related_name="benefits")
    benefit_type = models.CharField(max_length=40); value = models.JSONField(default=dict); is_active = models.BooleanField(default=True)
class MembershipAssignment(models.Model):
    customer = models.ForeignKey(CustomerProfile, on_delete=models.PROTECT, related_name="membership_assignments")
    tier = models.ForeignKey(MembershipTier, on_delete=models.PROTECT)
    is_active = models.BooleanField(default=True); starts_at = models.DateTimeField(auto_now_add=True); ends_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["customer"], condition=Q(is_active=True), name="one_active_membership")]
