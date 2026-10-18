from django.contrib import admin
from .models import Inventory, InventoryMovement
@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display=("product","available_quantity","reserved_quantity","sold_quantity","status")
    readonly_fields=("reserved_quantity","sold_quantity")
@admin.register(InventoryMovement)
class InventoryMovementAdmin(admin.ModelAdmin):
    list_display=("inventory","movement_type","quantity_delta","actor","created_at")
    readonly_fields=("inventory","movement_type","quantity_delta","reason","actor","created_at")
    def has_add_permission(self,request):return False
    def has_change_permission(self,request,obj=None):return False
    def has_delete_permission(self,request,obj=None):return False
