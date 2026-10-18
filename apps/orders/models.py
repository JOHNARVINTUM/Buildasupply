import uuid
from django.conf import settings
from django.db import models
from apps.customers.models import CustomerProfile
from apps.suppliers.models import Supplier
from apps.catalog.models import Product
class MasterOrder(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False); order_number=models.CharField(max_length=24,unique=True); customer=models.ForeignKey(CustomerProfile,on_delete=models.PROTECT,related_name="orders")
    currency=models.CharField(max_length=3,default="PHP"); subtotal_minor=models.PositiveBigIntegerField(); discount_minor=models.PositiveBigIntegerField(default=0); tax_minor=models.PositiveBigIntegerField(default=0); platform_fee_minor=models.PositiveBigIntegerField(default=0); delivery_fee_minor=models.PositiveBigIntegerField(default=0); total_minor=models.PositiveBigIntegerField()
    payment_status=models.CharField(max_length=24,default="PENDING"); status=models.CharField(max_length=32,default="PENDING_PAYMENT"); membership_snapshot=models.JSONField(default=dict); placed_at=models.DateTimeField(auto_now_add=True)
class SupplierOrder(models.Model):
    class Status(models.TextChoices): PENDING_PAYMENT="PENDING_PAYMENT","Pending payment"; PAID="PAID","Paid"; PENDING_SUPPLIER="PENDING_SUPPLIER","Pending supplier"; CONFIRMED="CONFIRMED","Confirmed"; PREPARING="PREPARING","Preparing"; READY_FOR_DELIVERY="READY_FOR_DELIVERY","Ready"; SHIPPED="SHIPPED","Shipped"; DELIVERED="DELIVERED","Delivered"; COMPLETED="COMPLETED","Completed"; CANCELLATION_REQUESTED="CANCELLATION_REQUESTED","Cancellation requested"; CANCELLED="CANCELLED","Cancelled"
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False); master_order=models.ForeignKey(MasterOrder,on_delete=models.PROTECT,related_name="supplier_orders"); supplier=models.ForeignKey(Supplier,on_delete=models.PROTECT,related_name="supplier_orders")
    supplier_name_snapshot=models.CharField(max_length=255); status=models.CharField(max_length=32,choices=Status.choices,default=Status.PENDING_PAYMENT); subtotal_minor=models.PositiveBigIntegerField(); discount_minor=models.PositiveBigIntegerField(default=0); tax_minor=models.PositiveBigIntegerField(default=0); platform_fee_minor=models.PositiveBigIntegerField(default=0); delivery_fee_minor=models.PositiveBigIntegerField(default=0); total_minor=models.PositiveBigIntegerField(); currency=models.CharField(max_length=3,default="PHP")
    class Meta: constraints=[models.UniqueConstraint(fields=["master_order","supplier"],name="one_supplier_order_per_checkout")];indexes=[models.Index(fields=["supplier","status"])]
class OrderItem(models.Model):
    supplier_order=models.ForeignKey(SupplierOrder,on_delete=models.PROTECT,related_name="items"); product=models.ForeignKey(Product,on_delete=models.PROTECT,null=True,blank=True)
    product_id_snapshot=models.UUIDField(); product_name=models.CharField(max_length=255); sku=models.CharField(max_length=80); unit_of_measure=models.CharField(max_length=32); supplier_id_snapshot=models.UUIDField(); supplier_name_snapshot=models.CharField(max_length=255)
    unit_price_minor=models.PositiveBigIntegerField(); quantity=models.PositiveIntegerField(); discount_minor=models.PositiveBigIntegerField(default=0); tax_minor=models.PositiveBigIntegerField(default=0); platform_fee_minor=models.PositiveBigIntegerField(default=0); line_total_minor=models.PositiveBigIntegerField(); currency=models.CharField(max_length=3,default="PHP")
class OrderFinancialLine(models.Model):
    master_order=models.ForeignKey(MasterOrder,on_delete=models.PROTECT,related_name="financial_lines"); supplier_order=models.ForeignKey(SupplierOrder,on_delete=models.PROTECT,null=True,blank=True,related_name="financial_lines"); line_type=models.CharField(max_length=32); source=models.CharField(max_length=64,default="CHECKOUT"); description=models.CharField(max_length=255); amount_minor=models.BigIntegerField(); currency=models.CharField(max_length=3); calculation_basis=models.JSONField(default=dict); rule_version=models.CharField(max_length=64,blank=True)
class Delivery(models.Model):
    supplier_order=models.OneToOneField(SupplierOrder,on_delete=models.PROTECT,related_name="delivery"); address_snapshot=models.JSONField(); status=models.CharField(max_length=16,default="PENDING"); carrier_name=models.CharField(max_length=120,blank=True); tracking_reference=models.CharField(max_length=120,blank=True); notes=models.TextField(blank=True); shipped_at=models.DateTimeField(null=True,blank=True); delivered_at=models.DateTimeField(null=True,blank=True)
class CheckoutIdempotency(models.Model):
    customer=models.ForeignKey(CustomerProfile,on_delete=models.PROTECT); key=models.CharField(max_length=128); fingerprint=models.CharField(max_length=64); master_order=models.OneToOneField(MasterOrder,on_delete=models.PROTECT,null=True,blank=True); created_at=models.DateTimeField(auto_now_add=True)
    class Meta: constraints=[models.UniqueConstraint(fields=["customer","key"],name="unique_customer_checkout_key")]
