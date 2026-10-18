from django.conf import settings
from django.db import models
class CustomerProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="customer_profile")
    full_name = models.CharField(max_length=160)
    phone = models.CharField(max_length=32)
    created_at, updated_at = models.DateTimeField(auto_now_add=True), models.DateTimeField(auto_now=True)
    def __str__(self): return self.full_name
class CustomerAddress(models.Model):
    customer=models.ForeignKey(CustomerProfile,on_delete=models.PROTECT,related_name="addresses")
    recipient_name=models.CharField(max_length=160); phone=models.CharField(max_length=32); address_line1=models.CharField(max_length=255); address_line2=models.CharField(max_length=255,blank=True)
    barangay=models.CharField(max_length=120,blank=True); city=models.CharField(max_length=120); province=models.CharField(max_length=120); postal_code=models.CharField(max_length=24,blank=True); country=models.CharField(max_length=2,default="PH"); is_default=models.BooleanField(default=False)
