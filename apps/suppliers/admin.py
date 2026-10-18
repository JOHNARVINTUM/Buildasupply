from django.contrib import admin
from .models import Supplier, SupplierStaffMembership, SupplierVerificationDocument
admin.site.register((Supplier, SupplierStaffMembership, SupplierVerificationDocument))
