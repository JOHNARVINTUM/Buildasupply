import uuid
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
class Supplier(models.Model):
    class ApprovalStatus(models.TextChoices): PENDING_REVIEW = "PENDING_REVIEW", "Pending review"; APPROVED = "APPROVED", "Approved"; SUSPENDED = "SUSPENDED", "Suspended"; REJECTED = "REJECTED", "Rejected"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    legal_name, display_name = models.CharField(max_length=255), models.CharField(max_length=255)
    email, phone = models.EmailField(), models.CharField(max_length=32)
    contact_name = models.CharField(max_length=160, blank=True)
    business_address = models.CharField(max_length=500, blank=True)
    business_registration_number = models.CharField(max_length=80, null=True, blank=True, unique=True)
    approval_status = models.CharField(max_length=20, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING_REVIEW)
    operational_status = models.CharField(max_length=12, choices=[("ACTIVE", "Active"), ("INACTIVE", "Inactive")], default="ACTIVE")
    review_reason = models.TextField(blank=True)
    created_at, updated_at = models.DateTimeField(auto_now_add=True), models.DateTimeField(auto_now=True)
    class Meta:
        indexes = [models.Index(fields=["approval_status", "display_name"])]
        constraints = [models.UniqueConstraint(Lower("legal_name"), name="unique_supplier_legal_name_ci")]
    def __str__(self): return self.display_name
class SupplierStaffMembership(models.Model):
    class Role(models.TextChoices): OWNER = "OWNER", "Owner"; MANAGER = "MANAGER", "Manager"; CATALOG_MANAGER = "CATALOG_MANAGER", "Catalog manager"; INVENTORY_MANAGER = "INVENTORY_MANAGER", "Inventory manager"; FULFILLMENT_MANAGER = "FULFILLMENT_MANAGER", "Fulfillment manager"; FINANCE_VIEWER = "FINANCE_VIEWER", "Finance viewer"
    class Status(models.TextChoices): INVITED = "INVITED", "Invited"; ACTIVE = "ACTIVE", "Active"; REVOKED = "REVOKED", "Revoked"
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="staff_memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="supplier_memberships")
    role = models.CharField(max_length=24, choices=Role.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    invited_at = models.DateTimeField(auto_now_add=True); accepted_at = models.DateTimeField(null=True, blank=True)
    created_at, updated_at = models.DateTimeField(auto_now_add=True), models.DateTimeField(auto_now=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["supplier", "user"], name="unique_supplier_staff"), models.UniqueConstraint(fields=["user"], condition=Q(status="ACTIVE"), name="one_active_supplier_membership")]
        indexes = [models.Index(fields=["supplier", "status"]), models.Index(fields=["user", "status"])]
class SupplierVerificationDocument(models.Model):
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="verification_documents")
    document_type = models.CharField(max_length=64)
    storage_key = models.CharField(max_length=512)  # private object-storage key, never public URL
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    status = models.CharField(max_length=20, default="PENDING")
    uploaded_at = models.DateTimeField(auto_now_add=True)
