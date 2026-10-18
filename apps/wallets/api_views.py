from rest_framework.response import Response
from rest_framework.views import APIView
from apps.wallets.services import balances,get_wallet
from apps.accounts.permissions import can_view_finance
class WalletView(APIView):
    def get(self,request):
        membership=request.user.supplier_memberships.filter(status="ACTIVE").select_related("supplier").first() if request.user.is_authenticated else None
        if not membership or not can_view_finance(request.user,membership.supplier):return Response({"detail":"Not found."},status=404)
        wallet=get_wallet(membership.supplier);return Response({"currency":wallet.currency,**balances(wallet)})
class TransactionsView(WalletView):
    def get(self,request):
        membership=request.user.supplier_memberships.filter(status="ACTIVE").select_related("supplier").first() if request.user.is_authenticated else None
        if not membership or not can_view_finance(request.user,membership.supplier):return Response({"detail":"Not found."},status=404)
        wallet=get_wallet(membership.supplier);return Response([{"type":e.entry_type,"bucket":e.bucket,"amount_minor":e.amount_minor,"reference":e.reference,"status":e.status} for e in wallet.entries.order_by("-created_at")[:100]])
