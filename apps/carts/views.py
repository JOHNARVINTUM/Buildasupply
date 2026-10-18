from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from apps.catalog.selectors import customer_catalog_queryset
from .services import get_active_cart, validate_cart
def browse(request): return render(request,"carts/browse.html",{"products":customer_catalog_queryset()[:24]})
def product_detail(request,pk):
    product=customer_catalog_queryset().filter(pk=pk).first()
    return render(request,"carts/product_detail.html",{"product":product},status=200 if product else 404)
@login_required
def cart_page(request):
    if not hasattr(request.user,"customer_profile"):return render(request,"carts/cart.html",{"denied":True})
    cart=get_active_cart(request.user.customer_profile)
    return render(request,"carts/cart.html",{"cart":cart,"validation":validate_cart(cart)})
@login_required
def checkout_page(request):
    if not hasattr(request.user,"customer_profile"):return render(request,"carts/checkout.html",{"denied":True})
    cart=get_active_cart(request.user.customer_profile)
    return render(request,"carts/checkout.html",{"cart":cart,"validation":validate_cart(cart)})
@login_required
def order_history(request):
    from apps.orders.models import MasterOrder
    orders=MasterOrder.objects.filter(customer=request.user.customer_profile).order_by("-placed_at") if hasattr(request.user,"customer_profile") else []
    return render(request,"carts/orders.html",{"orders":orders})
@login_required
def payment_status(request,pk):
    from apps.payments.models import Payment
    payment=Payment.objects.select_related("master_order").filter(pk=pk,master_order__customer=getattr(request.user,"customer_profile",None)).first()
    return render(request,"carts/payment_status.html",{"payment":payment},status=200 if payment else 404)
