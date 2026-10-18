from rest_framework.response import Response
from rest_framework.views import APIView
from apps.wallets.services import get_wallet
from .models import PayoutMethod
from .services import request_payout
from apps.accounts.permissions import can_view_finance
class PayoutMethodsView(APIView):
    def get(self,request):
        m=request.user.supplier_memberships.filter(status="ACTIVE").select_related("supplier").first() if request.user.is_authenticated else None
        if not m or not can_view_finance(request.user,m.supplier):return Response({"detail":"Not found."},status=404)
        w=get_wallet(m.supplier);return Response([{"id":x.id,"type":x.method_type,"masked_destination":x.masked_destination,"preferred":x.is_preferred} for x in w.payout_methods.filter(is_active=True)])
class PayoutsView(PayoutMethodsView):
    def post(self,request):
        m=request.user.supplier_memberships.filter(status="ACTIVE").select_related("supplier").first() if request.user.is_authenticated else None
        if not m or not can_view_finance(request.user,m.supplier):return Response({"detail":"Not found."},status=404)
        try:p=request_payout(get_wallet(m.supplier),PayoutMethod.objects.get(pk=request.data["method_id"]),int(request.data["amount_minor"]),request.user,request.headers.get("Idempotency-Key"));return Response({"id":str(p.id),"status":p.status},status=201)
        except Exception as exc:return Response({"detail":str(exc)},status=400)
