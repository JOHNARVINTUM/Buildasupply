from django.core.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.accounts.permissions import IsActiveAccount, can_manage_inventory, can_view_finance
from .models import Inventory
from .services import record_movement
def accessible(user, inventory, write=False):
    if user.primary_role=="SUPERADMIN": return True
    return (can_manage_inventory if write else lambda u,s:can_manage_inventory(u,s) or can_view_finance(u,s))(user,inventory.product.supplier)
class InventoryDetailView(APIView):
    permission_classes=[IsActiveAccount]
    def get_object(self,request,pk):
        item=Inventory.objects.select_related("product__supplier").filter(pk=pk).first()
        return item if item and accessible(request.user,item) else None
    def get(self,request,pk):
        item=self.get_object(request,pk)
        return Response({"detail":"Not found."},status=404) if not item else Response({"id":item.id,"available_quantity":item.available_quantity,"status":item.status})
class InventoryActionView(InventoryDetailView):
    def post(self,request,pk):
        item=self.get_object(request,pk)
        if not item or not accessible(request.user,item,True):return Response({"detail":"Not found."},status=404)
        try: movement=record_movement(inventory_id=item.id,actor=request.user,movement_type=request.data["movement_type"],quantity_delta=int(request.data["quantity_delta"]),reason=request.data.get("reason",""))
        except (KeyError,ValueError,ValidationError) as exc:return Response({"detail":str(exc)},status=400)
        return Response({"movement_id":str(movement.id),"available_quantity":item.available_quantity})
class InventoryMovementView(InventoryDetailView):
    def get(self,request,pk):
        item=self.get_object(request,pk)
        if not item:return Response({"detail":"Not found."},status=404)
        return Response([{"id":str(m.id),"type":m.movement_type,"delta":m.quantity_delta,"reason":m.reason} for m in item.movements.all().order_by("-created_at")[:100]])
