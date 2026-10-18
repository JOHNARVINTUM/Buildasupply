from rest_framework.permissions import BasePermission
from apps.suppliers.models import SupplierStaffMembership
class IsActiveAccount(BasePermission):
    def has_permission(self, request, view): return bool(request.user and request.user.is_authenticated and request.user.account_status == "ACTIVE")
class IsCustomer(IsActiveAccount):
    def has_permission(self, request, view): return super().has_permission(request, view) and request.user.primary_role == "CUSTOMER"
class IsSupplier(IsActiveAccount):
    def has_permission(self, request, view): return super().has_permission(request, view) and request.user.primary_role == "SUPPLIER"
class IsApprovedSupplier(IsSupplier):
    def has_permission(self, request, view): return super().has_permission(request, view) and request.user.supplier_memberships.filter(status="ACTIVE", supplier__approval_status="APPROVED").exists()
class IsSuperadmin(IsActiveAccount):
    def has_permission(self, request, view): return super().has_permission(request, view) and request.user.primary_role == "SUPERADMIN"
def membership_for(user, supplier): return SupplierStaffMembership.objects.filter(user=user, supplier=supplier, status="ACTIVE").first()
def can_manage_supplier(user, supplier, roles):
    membership = membership_for(user, supplier)
    return user.primary_role == "SUPERADMIN" or bool(membership and membership.role in roles)
def can_manage_catalog(user, supplier): return can_manage_supplier(user, supplier, {"OWNER", "MANAGER", "CATALOG_MANAGER"})
def can_manage_inventory(user, supplier): return can_manage_supplier(user, supplier, {"OWNER", "MANAGER", "INVENTORY_MANAGER"})
def can_manage_fulfillment(user, supplier): return can_manage_supplier(user, supplier, {"OWNER", "MANAGER", "FULFILLMENT_MANAGER"})
def can_view_finance(user, supplier): return can_manage_supplier(user, supplier, {"OWNER", "MANAGER", "FINANCE_VIEWER"})
