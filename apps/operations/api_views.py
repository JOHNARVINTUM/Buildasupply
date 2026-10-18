from django.db.models import Count,Sum
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.accounts.permissions import IsSuperadmin
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.catalog.models import Product
from apps.core.models import BusinessConfiguration
from apps.orders.models import MasterOrder
from apps.payments.models import Payment,Refund
from apps.payouts.models import PayoutRequest
from apps.suppliers.models import Supplier
from apps.wallets.models import Wallet
from apps.wallets.services import reconcile
from .services import set_configuration
class AdminBase(APIView): permission_classes=[IsSuperadmin]
class DashboardView(AdminBase):
    def get(self,request):
        today=timezone.localdate()
        wallets=Wallet.objects.aggregate(pending=Sum("pending_cached"),available=Sum("available_cached"))
        return Response({"attention":{"pending_suppliers":Supplier.objects.filter(approval_status="PENDING_REVIEW").count(),"pending_products":Product.objects.filter(status="PENDING_REVIEW").count(),"failed_payments":Payment.objects.filter(status="FAILED").count(),"pending_payouts":PayoutRequest.objects.filter(status="REQUESTED").count(),"pending_refunds":Refund.objects.filter(status__in=["REQUESTED","PROCESSING"]).count()},"metrics":{"orders_today":MasterOrder.objects.filter(placed_at__date=today).count(),"gross_value_minor":MasterOrder.objects.aggregate(x=Sum("total_minor"))["x"] or 0,"successful_payments":Payment.objects.filter(status="PAID").count(),"pending_funds_minor":wallets["pending"] or 0,"available_funds_minor":wallets["available"] or 0},"recent_actions":[{"action":x.action,"target":x.target_type,"at":x.created_at} for x in AuditLog.objects.select_related("actor").order_by("-created_at")[:10]]})
class AdminCollectionView(AdminBase):
    def get(self,request,resource):
        limit=min(int(request.query_params.get("limit",25)),100);query=request.query_params.get("q","")
        tables={"users":(User,"email"),"suppliers":(Supplier,"display_name"),"products":(Product,"name"),"orders":(MasterOrder,"order_number"),"payments":(Payment,"internal_reference"),"refunds":(Refund,"reference"),"payouts":(PayoutRequest,"status"),"audit":(AuditLog,"action")}
        if resource not in tables:return Response({"detail":"Not found."},status=404)
        model,field=tables[resource];qs=model.objects.all().order_by("-pk")
        if query:qs=qs.filter(**{f"{field}__icontains":query})
        return Response([{"id":str(x.pk),"label":str(x),"created_at":getattr(x,"created_at",None)} for x in qs[:limit]])
class ConfigurationView(AdminBase):
    def get(self,request):return Response([{"key":c.key,"version":c.version,"active":c.is_active,"value":c.value} for c in BusinessConfiguration.objects.order_by("key","-created_at")])
    def post(self,request):
        from django.utils.dateparse import parse_datetime
        try:c=set_configuration(actor=request.user,key=request.data["key"],version=request.data["version"],value=request.data["value"],effective_from=parse_datetime(request.data["effective_from"]),effective_to=parse_datetime(request.data.get("effective_to")) if request.data.get("effective_to") else None,activate=bool(request.data.get("activate")));return Response({"id":c.id},status=201)
        except Exception as exc:return Response({"detail":str(exc)},status=400)
class SupplierActionView(AdminBase):
    def post(self,request,pk,action):
        from apps.catalog.services import transition_supplier
        supplier=Supplier.objects.filter(pk=pk).first()
        if not supplier:return Response({"detail":"Not found."},status=404)
        try:transition_supplier(supplier=supplier,actor=request.user,status={"approve":"APPROVED","reject":"REJECTED","suspend":"SUSPENDED","reinstate":"APPROVED"}[action],reason=request.data.get("reason",""));return Response({"status":supplier.approval_status})
        except Exception as exc:return Response({"detail":str(exc)},status=400)
