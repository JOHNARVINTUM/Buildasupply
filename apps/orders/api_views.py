from django.core.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import MasterOrder, SupplierOrder
from .services import CheckoutFailure, checkout
class CheckoutView(APIView):
    def post(self,request):
        if not hasattr(request.user,"customer_profile"):return Response({"detail":"Customer access required."},status=403)
        try:return Response(checkout(customer=request.user.customer_profile,idempotency_key=request.headers.get("Idempotency-Key")),status=201)
        except CheckoutFailure as exc:return Response(exc.message_dict,status=400)
class CustomerOrdersView(APIView):
    def get(self,request):
        if not hasattr(request.user,"customer_profile"):return Response({"detail":"Customer access required."},status=403)
        return Response([{"id":str(o.id),"number":o.order_number,"status":o.status,"total_minor":o.total_minor,"currency":o.currency} for o in MasterOrder.objects.filter(customer=request.user.customer_profile).order_by("-placed_at")])
class CustomerOrderDetailView(APIView):
    def get(self,request,pk):
        if not hasattr(request.user,"customer_profile"):return Response({"detail":"Not found."},status=404)
        o=MasterOrder.objects.filter(pk=pk,customer=request.user.customer_profile).prefetch_related("supplier_orders__items").first()
        if not o:return Response({"detail":"Not found."},status=404)
        return Response({"number":o.order_number,"total_minor":o.total_minor,"supplier_orders":[{"supplier":s.supplier_name_snapshot,"status":s.status,"items":[{"name":i.product_name,"quantity":i.quantity,"unit_price_minor":i.unit_price_minor} for i in s.items.all()]} for s in o.supplier_orders.all()]})
class SupplierOrdersView(APIView):
    def get(self,request):
        memberships=request.user.supplier_memberships.filter(status="ACTIVE").values_list("supplier_id",flat=True) if request.user.is_authenticated else []
        return Response([{"id":str(o.id),"order_number":o.master_order.order_number,"status":o.status,"total_minor":o.total_minor} for o in SupplierOrder.objects.filter(supplier_id__in=memberships).select_related("master_order")])
