from django.db import models
from django.db.models import Q
from apps.customers.models import CustomerProfile
from apps.catalog.models import Product
class Cart(models.Model):
    class Status(models.TextChoices): ACTIVE="ACTIVE", "Active"; CHECKED_OUT="CHECKED_OUT", "Checked out"; ABANDONED="ABANDONED", "Abandoned"
    customer=models.ForeignKey(CustomerProfile,on_delete=models.PROTECT,related_name="carts"); currency=models.CharField(max_length=3,default="PHP"); status=models.CharField(max_length=16,choices=Status.choices,default=Status.ACTIVE)
    created_at=models.DateTimeField(auto_now_add=True); updated_at=models.DateTimeField(auto_now=True)
    class Meta: constraints=[models.UniqueConstraint(fields=["customer","currency"],condition=Q(status="ACTIVE"),name="one_active_cart_per_currency")]
class CartItem(models.Model):
    cart=models.ForeignKey(Cart,on_delete=models.CASCADE,related_name="items"); product=models.ForeignKey(Product,on_delete=models.PROTECT,related_name="cart_items")
    quantity=models.PositiveIntegerField(); displayed_price_minor=models.PositiveBigIntegerField(); displayed_currency=models.CharField(max_length=3,default="PHP")
    created_at=models.DateTimeField(auto_now_add=True); updated_at=models.DateTimeField(auto_now=True)
    class Meta: constraints=[models.UniqueConstraint(fields=["cart","product"],name="unique_cart_product"),models.CheckConstraint(condition=Q(quantity__gt=0),name="cart_quantity_positive")]
