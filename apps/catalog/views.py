from django.contrib.auth.decorators import login_required
from django.db import models
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from apps.accounts.permissions import can_manage_catalog
from apps.inventory.services import record_movement
from apps.inventory.models import Inventory
from .forms import ProductCreateForm, ProductEditForm
from .models import Category, Product
from .services import create_product, current_price_for, submit_for_review, update_product, update_product_price
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
def product_create(request):
    membership=request.user.supplier_memberships.filter(status="ACTIVE").select_related("supplier").first()
    if not membership or not can_manage_catalog(request.user, membership.supplier): return redirect("accounts:profile")
    form=ProductCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        category=form.cleaned_data["category"]
        if not category:
            category, _=Category.objects.get_or_create(slug="general-supplies", defaults={"name":"General Supplies", "description":"General marketplace supplies", "is_active":True})
        try:
            product=create_product(supplier=membership.supplier, actor=request.user, category=category, name=form.cleaned_data["name"], sku=form.cleaned_data["sku"], description=form.cleaned_data["description"], unit_of_measure=form.cleaned_data["unit_of_measure"], minimum_order_quantity=form.cleaned_data["minimum_order_quantity"], amount_minor=form.amount_minor())
            if form.cleaned_data["opening_stock"]:
                record_movement(inventory_id=product.inventory.id, actor=request.user, movement_type="RESTOCK", quantity_delta=form.cleaned_data["opening_stock"], reason="Opening stock")
            messages.success(request, "Supply draft created. Submit it for review when ready.")
            return redirect("supplier-products")
        except ValidationError as exc: form.add_error(None, exc)
    return render(request, "catalog/product_form.html", {"form":form, "supplier":membership.supplier})

@login_required
def product_edit(request, pk):
    membership=request.user.supplier_memberships.filter(status="ACTIVE").select_related("supplier").first()
    if not membership or not can_manage_catalog(request.user, membership.supplier): return redirect("accounts:profile")
    product=Product.objects.filter(pk=pk, supplier=membership.supplier).select_related("inventory", "category").first()
    if not product: return redirect("supplier-products")
    price=current_price_for(product)
    initial={"name":product.name,"sku":product.sku,"category":product.category,"description":product.description,"unit_of_measure":product.unit_of_measure,"minimum_order_quantity":product.minimum_order_quantity,"price_php":(price.amount_minor / 100) if price else None,"stock_quantity":product.inventory.available_quantity}
    form=ProductEditForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            update_product(product=product, actor=request.user, name=form.cleaned_data["name"], sku=form.cleaned_data["sku"], category=form.cleaned_data["category"], description=form.cleaned_data["description"], unit_of_measure=form.cleaned_data["unit_of_measure"], minimum_order_quantity=form.cleaned_data["minimum_order_quantity"])
            update_product_price(product=product, actor=request.user, amount_minor=form.amount_minor())
            delta=form.cleaned_data["stock_quantity"]-product.inventory.available_quantity
            if delta: record_movement(inventory_id=product.inventory.id, actor=request.user, movement_type="ADJUSTMENT", quantity_delta=delta, reason="Supplier catalog update")
            messages.success(request, "Supply updated.")
            return redirect("supplier-products")
        except ValidationError as exc: form.add_error(None, exc)
    return render(request, "catalog/product_edit.html", {"form":form,"product":product,"supplier":membership.supplier})

@login_required
def product_submit(request, pk):
    if request.method != "POST": return redirect("supplier-products")
    membership=request.user.supplier_memberships.filter(status="ACTIVE").select_related("supplier").first()
    if not membership or not can_manage_catalog(request.user, membership.supplier): return redirect("accounts:profile")
    product=Product.objects.filter(pk=pk, supplier=membership.supplier).first()
    if not product: return redirect("supplier-products")
    try:
        submit_for_review(product=product, actor=request.user)
        messages.success(request, f"{product.name} was submitted for review.")
    except ValidationError as exc: messages.error(request, "; ".join(exc.messages))
    return redirect("supplier-products")
@login_required
def wallet_page(request):
    membership=request.user.supplier_memberships.filter(status="ACTIVE").select_related("supplier").first()
    if not membership:return redirect("accounts:profile")
    from apps.wallets.services import balances,get_wallet
    wallet=get_wallet(membership.supplier)
    return render(request,"catalog/wallet.html",{"wallet":wallet,"balances":balances(wallet),"entries":wallet.entries.order_by("-created_at")[:20],"settlements":wallet.settlements.exclude(status="RELEASED")[:10]})
