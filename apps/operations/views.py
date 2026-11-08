from django.contrib.auth.decorators import user_passes_test
from django.db.models import Sum
from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from apps.audit.models import AuditLog
from apps.catalog.models import Product
from apps.payments.models import Payment
from apps.payouts.models import PayoutRequest
from apps.suppliers.models import Supplier
from apps.catalog.services import moderate_product, transition_supplier
from apps.wallets.models import Wallet
from apps.accounts.models import User
from apps.accounts.services import set_account_status
def admin_required(view):return user_passes_test(lambda u:u.is_authenticated and u.primary_role=="SUPERADMIN")(view)
@admin_required
def dashboard(request):
    wallet=Wallet.objects.aggregate(pending=Sum("pending_cached"),available=Sum("available_cached"))
    return render(request,"operations/dashboard.html",{"pending_suppliers":Supplier.objects.filter(approval_status="PENDING_REVIEW").count(),"pending_products":Product.objects.filter(status="PENDING_REVIEW").count(),"failed_payments":Payment.objects.filter(status="FAILED").count(),"pending_payouts":PayoutRequest.objects.filter(status="REQUESTED").count(),"wallet":wallet,"actions":AuditLog.objects.order_by("-created_at")[:12]})
@admin_required
def audit_view(request):return render(request,"operations/audit.html",{"logs":AuditLog.objects.select_related("actor").order_by("-created_at")[:100]})

@admin_required
def users(request):
    query=request.GET.get("q", "").strip()
    accounts=User.objects.order_by("email")
    if query: accounts=accounts.filter(email__icontains=query)
    page=Paginator(accounts, 25).get_page(request.GET.get("page"))
    return render(request, "operations/users.html", {"page": page, "query": query})

@admin_required
def update_user_status(request, pk):
    if request.method != "POST": return redirect("operations-users")
    account=get_object_or_404(User, pk=pk)
    status=request.POST.get("status")
    allowed={choice for choice, _ in User.AccountStatus.choices}
    if account == request.user:
        messages.error(request, "You cannot change your own account status here.")
    elif status not in allowed:
        messages.error(request, "Invalid account status.")
    else:
        set_account_status(user=account, actor=request.user, status=status)
        messages.success(request, f"Updated {account.email} to {status.replace('_', ' ').title()}.")
    return redirect("operations-users")

@admin_required
def suppliers(request):
    query=request.GET.get("q", "").strip()
    suppliers=Supplier.objects.order_by("approval_status", "display_name")
    if query: suppliers=suppliers.filter(display_name__icontains=query)
    page=Paginator(suppliers, 25).get_page(request.GET.get("page"))
    return render(request, "operations/suppliers.html", {"page": page, "query": query})

@admin_required
def update_supplier_status(request, pk):
    if request.method != "POST": return redirect("operations-suppliers")
    supplier=get_object_or_404(Supplier, pk=pk)
    status=request.POST.get("status")
    try:
        transition_supplier(supplier=supplier, actor=request.user, status=status, reason=request.POST.get("reason", ""))
        messages.success(request, f"Updated {supplier.display_name} to {status.replace('_', ' ').title()}.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("operations-suppliers")

@admin_required
def supplier_products(request, pk):
    supplier=get_object_or_404(Supplier, pk=pk)
    products=Product.objects.filter(supplier=supplier).select_related("category", "inventory").order_by("-updated_at")
    return render(request, "operations/supplier_products.html", {"supplier":supplier, "products":products})

@admin_required
def update_product_status(request, supplier_pk, product_pk):
    if request.method != "POST": return redirect("operations-supplier-products", pk=supplier_pk)
    supplier=get_object_or_404(Supplier, pk=supplier_pk)
    product=get_object_or_404(Product, pk=product_pk, supplier=supplier)
    action=request.POST.get("action")
    try:
        moderate_product(product=product, actor=request.user, approve=action == "approve", reason=request.POST.get("reason", ""))
        messages.success(request, f"Updated {product.name}.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("operations-supplier-products", pk=supplier.pk)
