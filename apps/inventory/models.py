import uuid
from django.conf import settings
from django.db import models
from django.db.models import Q
from apps.catalog.models import Product
class Inventory(models.Model):
    class Status(models.TextChoices): ACTIVE="ACTIVE", "Active"; OUT_OF_STOCK="OUT_OF_STOCK", "Out of stock"; DISABLED="DISABLED", "Disabled"
    product = models.OneToOneField(Product, on_delete=models.PROTECT, related_name="inventory")
    available_quantity=models.PositiveIntegerField(default=0); reserved_quantity=models.PositiveIntegerField(default=0); sold_quantity=models.PositiveIntegerField(default=0)
    low_stock_threshold=models.PositiveIntegerField(default=0); status=models.CharField(max_length=16, choices=Status.choices, default=Status.OUT_OF_STOCK); updated_at=models.DateTimeField(auto_now=True)
    class Meta: constraints=[models.CheckConstraint(condition=Q(available_quantity__gte=0)&Q(reserved_quantity__gte=0)&Q(sold_quantity__gte=0), name="inventory_quantities_nonnegative")]
class InventoryMovement(models.Model):
    class Type(models.TextChoices): RESTOCK="RESTOCK", "Restock"; ADJUSTMENT="ADJUSTMENT", "Adjustment"; CORRECTION="CORRECTION", "Correction"; DAMAGE="DAMAGE", "Damage"; RETURN="RETURN", "Return"; RESERVATION="RESERVATION", "Reservation"; RESERVATION_RELEASE="RESERVATION_RELEASE", "Reservation release"; SALE="SALE", "Sale"
    id=models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False); inventory=models.ForeignKey(Inventory, on_delete=models.PROTECT, related_name="movements")
    movement_type=models.CharField(max_length=24, choices=Type.choices); quantity_delta=models.IntegerField(); reason=models.CharField(max_length=500); actor=models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    reference_type=models.CharField(max_length=100, blank=True); reference_id=models.UUIDField(null=True, blank=True); created_at=models.DateTimeField(auto_now_add=True)
    class Meta: constraints=[models.CheckConstraint(condition=~Q(quantity_delta=0), name="movement_delta_nonzero")]; indexes=[models.Index(fields=["inventory", "created_at"])]
class InventoryReservation(models.Model):
    class Status(models.TextChoices): ACTIVE="ACTIVE","Active"; CONSUMED="CONSUMED","Consumed"; RELEASED="RELEASED","Released"; EXPIRED="EXPIRED","Expired"
    inventory=models.ForeignKey(Inventory,on_delete=models.PROTECT,related_name="reservations"); quantity=models.PositiveIntegerField(); status=models.CharField(max_length=12,choices=Status.choices,default=Status.ACTIVE)
    supplier_order=models.ForeignKey("orders.SupplierOrder",on_delete=models.PROTECT,related_name="inventory_reservations"); expires_at=models.DateTimeField(); created_at=models.DateTimeField(auto_now_add=True); updated_at=models.DateTimeField(auto_now=True)
    class Meta: constraints=[models.CheckConstraint(condition=Q(quantity__gt=0),name="reservation_quantity_positive")]; indexes=[models.Index(fields=["inventory","status","expires_at"])]
