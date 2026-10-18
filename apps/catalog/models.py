import uuid
from django.conf import settings
from django.db import models
from django.db.models import Q
from apps.suppliers.models import Supplier
class Category(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")
    name = models.CharField(max_length=120); slug = models.SlugField(unique=True); description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True); display_order = models.PositiveIntegerField(default=0)
    class Meta: indexes = [models.Index(fields=["parent", "is_active", "display_order"])]
    def clean(self):
        if self.parent_id == self.id: from django.core.exceptions import ValidationError; raise ValidationError("A category cannot be its own parent.")
        ancestor = self.parent
        while ancestor:
            if ancestor.pk == self.pk:
                from django.core.exceptions import ValidationError
                raise ValidationError("A category hierarchy cannot contain a cycle.")
            ancestor = ancestor.parent
class Product(models.Model):
    class Status(models.TextChoices): DRAFT="DRAFT", "Draft"; PENDING_REVIEW="PENDING_REVIEW", "Pending review"; APPROVED="APPROVED", "Approved"; REJECTED="REJECTED", "Rejected"; ARCHIVED="ARCHIVED", "Archived"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="products")
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.PROTECT, related_name="products")
    sku = models.CharField(max_length=80); name = models.CharField(max_length=255); description = models.TextField(blank=True); unit_of_measure = models.CharField(max_length=32)
    minimum_order_quantity = models.PositiveIntegerField(default=1); status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    public_availability = models.BooleanField(default=True); moderation_reason = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="reviewed_products")
    reviewed_at = models.DateTimeField(null=True, blank=True); created_at = models.DateTimeField(auto_now_add=True); updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=["supplier", "sku"], name="unique_supplier_sku"), models.CheckConstraint(condition=Q(minimum_order_quantity__gt=0), name="product_minimum_positive")]
        indexes=[models.Index(fields=["supplier", "status"]), models.Index(fields=["category", "status"]), models.Index(fields=["status", "public_availability"])]
class ProductPrice(models.Model):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="prices")
    amount_minor = models.PositiveBigIntegerField(); currency = models.CharField(max_length=3, default="PHP")
    starts_at = models.DateTimeField(); ends_at = models.DateTimeField(null=True, blank=True); is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[models.CheckConstraint(condition=Q(amount_minor__gt=0), name="product_price_positive"), models.UniqueConstraint(fields=["product", "currency"], condition=Q(is_active=True), name="one_active_product_price")]
        indexes=[models.Index(fields=["product", "currency", "starts_at"])]
class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    file = models.FileField(upload_to="catalog/products/%Y/%m/", max_length=500)
    display_order = models.PositiveIntegerField(default=0); alt_text = models.CharField(max_length=255, blank=True); is_primary = models.BooleanField(default=False); is_active = models.BooleanField(default=True)
    class Meta: constraints=[models.UniqueConstraint(fields=["product"], condition=Q(is_primary=True, is_active=True), name="one_primary_product_image")]
