from django.contrib.auth.decorators import login_required
from django.db import models
from django.shortcuts import redirect, render
from apps.inventory.models import Inventory
from .models import Product
@login_required
def dashboard(request):
    membership=request.user.supplier_memberships.filter(status="ACTIVE").select_related("supplier").first()
    if not membership:return redirect("accounts:profile")
    products=Product.objects.filter(supplier=membership.supplier).select_related("inventory")
    low=products.filter(inventory__available_quantity__lte=models.F("inventory__low_stock_threshold"))
    return render(request,"catalog/dashboard.html",{"supplier":membership.supplier,"products":products[:8],"low_stock":low.count(),"pending":products.filter(status="PENDING_REVIEW").count()})
@login_required
def product_list(request):
    membership=request.user.supplier_memberships.filter(status="ACTIVE").select_related("supplier").first()
    if not membership:return redirect("accounts:profile")
    products=Product.objects.filter(supplier=membership.supplier).select_related("category","inventory").order_by("-updated_at")
    if query:=request.GET.get("q"): products=products.filter(name__icontains=query)
    return render(request,"catalog/product_list.html",{"products":products,"supplier":membership.supplier})
@login_required
def wallet_page(request):
    membership=request.user.supplier_memberships.filter(status="ACTIVE").select_related("supplier").first()
    if not membership:return redirect("accounts:profile")
    from apps.wallets.services import balances,get_wallet
    wallet=get_wallet(membership.supplier)
    return render(request,"catalog/wallet.html",{"wallet":wallet,"balances":balances(wallet),"entries":wallet.entries.order_by("-created_at")[:20],"settlements":wallet.settlements.exclude(status="RELEASED")[:10]})
