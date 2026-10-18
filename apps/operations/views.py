from django.contrib.auth.decorators import user_passes_test
from django.db.models import Sum
from django.shortcuts import render
from apps.audit.models import AuditLog
from apps.catalog.models import Product
from apps.payments.models import Payment
from apps.payouts.models import PayoutRequest
from apps.suppliers.models import Supplier
from apps.wallets.models import Wallet
def admin_required(view):return user_passes_test(lambda u:u.is_authenticated and u.primary_role=="SUPERADMIN")(view)
@admin_required
def dashboard(request):
    wallet=Wallet.objects.aggregate(pending=Sum("pending_cached"),available=Sum("available_cached"))
    return render(request,"operations/dashboard.html",{"pending_suppliers":Supplier.objects.filter(approval_status="PENDING_REVIEW").count(),"pending_products":Product.objects.filter(status="PENDING_REVIEW").count(),"failed_payments":Payment.objects.filter(status="FAILED").count(),"pending_payouts":PayoutRequest.objects.filter(status="REQUESTED").count(),"wallet":wallet,"actions":AuditLog.objects.order_by("-created_at")[:12]})
@admin_required
def audit_view(request):return render(request,"operations/audit.html",{"logs":AuditLog.objects.select_related("actor").order_by("-created_at")[:100]})
