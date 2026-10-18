import uuid
from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from .managers import UserManager

class User(AbstractBaseUser, PermissionsMixin):
    class GlobalRole(models.TextChoices): CUSTOMER = "CUSTOMER", "Customer"; SUPPLIER = "SUPPLIER", "Supplier"; SUPERADMIN = "SUPERADMIN", "Superadmin"
    class AccountStatus(models.TextChoices): ACTIVE = "ACTIVE", "Active"; PENDING_VERIFICATION = "PENDING_VERIFICATION", "Pending verification"; SUSPENDED = "SUSPENDED", "Suspended"; DEACTIVATED = "DEACTIVATED", "Deactivated"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    primary_role = models.CharField(max_length=20, choices=GlobalRole.choices, default=GlobalRole.CUSTOMER)
    account_status = models.CharField(max_length=24, choices=AccountStatus.choices, default=AccountStatus.ACTIVE)
    is_staff, is_active = models.BooleanField(default=False), models.BooleanField(default=True)
    date_joined = models.DateTimeField(auto_now_add=True)
    created_at, updated_at = models.DateTimeField(auto_now_add=True), models.DateTimeField(auto_now=True)
    USERNAME_FIELD, REQUIRED_FIELDS, objects = "email", [], UserManager()
    class Meta: indexes = [models.Index(fields=["account_status", "primary_role"])]
    def save(self, *args, **kwargs):
        self.email = self.__class__.objects.normalize_email(self.email).lower()
        self.is_active = self.account_status == self.AccountStatus.ACTIVE
        return super().save(*args, **kwargs)
    def __str__(self): return self.email


class TermsAcceptance(models.Model):
    """The latest explicit acceptance captured at account creation."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="terms_acceptance")
    terms_version = models.CharField(max_length=32)
    privacy_version = models.CharField(max_length=32)
    accepted_at = models.DateTimeField(auto_now_add=True)
