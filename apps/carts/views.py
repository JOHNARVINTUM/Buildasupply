from collections import OrderedDict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from apps.catalog.selectors import customer_catalog_queryset
from .forms import CartQuantityForm
from .models import CartItem
from .services import add_item, get_active_cart, update_quantity, validate_cart


VALIDATION_MESSAGES = {
    "PRODUCT_ARCHIVED": "This product is no longer available.",
    "SUPPLIER_UNAVAILABLE": "This supplier is not currently available.",
    "PRODUCT_UNAVAILABLE": "This product is not currently available.",
    "OUT_OF_STOCK": "This product is out of stock.",
    "CURRENCY_CHANGED": "The product currency changed. Remove and add it again to continue.",
    "PRICE_CHANGED": "The price changed. Review the current price before checkout.",
    "MOQ_NOT_MET": "The quantity is below this product's minimum order quantity.",
    "INSUFFICIENT_STOCK": "The requested quantity is no longer available.",
}


def _customer_for(request):
    if (
        request.user.primary_role != "CUSTOMER"
        or request.user.account_status != "ACTIVE"
        or not hasattr(request.user, "customer_profile")
    ):
        raise PermissionDenied("Customer access is required.")
    return request.user.customer_profile


def _error_message(error):
    code = error.messages[0] if getattr(error, "messages", None) else str(error)
    return VALIDATION_MESSAGES.get(code, code)


def _cart_context(customer):
    cart = get_active_cart(customer)
    items = list(
        cart.items.select_related("product__supplier", "product__inventory")
        .prefetch_related("product__images")
        .order_by("product__supplier__display_name", "pk")
    )
    validation = validate_cart(cart)
    validation_by_item = {entry["item_id"]: entry for entry in validation["items"]}
    suppliers = OrderedDict()
    total_minor = 0
    for item in items:
        product = item.product
        image = next((image for image in product.images.all() if image.is_active and image.is_primary), None)
        image = image or next((image for image in product.images.all() if image.is_active), None)
        line_total = item.quantity * item.displayed_price_minor
        entry = validation_by_item[item.pk]
        line = {
            "item": item,
            "image": image,
            "subtotal_minor": line_total,
            "validation": entry,
            "validation_message": VALIDATION_MESSAGES.get(entry["reason"], "") if entry["reason"] else "",
            "form": CartQuantityForm(initial={"quantity": item.quantity}, minimum_order_quantity=product.minimum_order_quantity),
        }
        group = suppliers.setdefault(product.supplier_id, {"supplier": product.supplier, "lines": [], "subtotal_minor": 0})
        group["lines"].append(line)
        group["subtotal_minor"] += line_total
        total_minor += line_total
    return {
        "cart": cart,
        "validation": validation,
        "supplier_groups": list(suppliers.values()),
        "cart_total_minor": total_minor,
    }


def browse(request): return render(request,"carts/browse.html",{"products":customer_catalog_queryset()[:24]})
def product_detail(request,pk):
    product=customer_catalog_queryset().filter(pk=pk).first()
    form = CartQuantityForm(initial={"quantity": product.minimum_order_quantity}, minimum_order_quantity=product.minimum_order_quantity) if product else None
    return render(request,"carts/product_detail.html",{"product":product, "form": form},status=200 if product else 404)


@login_required
def add_to_cart(request, pk):
    if request.method != "POST":
        raise Http404
    customer = _customer_for(request)
    product = get_object_or_404(customer_catalog_queryset(), pk=pk)
    form = CartQuantityForm(request.POST, minimum_order_quantity=product.minimum_order_quantity)
    if form.is_valid():
        try:
            add_item(customer=customer, product=product, quantity=form.cleaned_data["quantity"])
        except ValidationError as error:
            form.add_error("quantity", _error_message(error))
        else:
            messages.success(request, f"{product.name} was added to your cart.")
            return redirect("shop-cart")
    messages.error(request, "Please correct the quantity before adding this product.")
    return render(request, "carts/product_detail.html", {"product": product, "form": form}, status=400)


@login_required
def cart_page(request):
    return render(request, "carts/cart.html", _cart_context(_customer_for(request)))


def _owned_item(customer, pk):
    return get_object_or_404(
        CartItem.objects.select_related("product__supplier", "product__inventory"),
        pk=pk,
        cart__customer=customer,
        cart__status="ACTIVE",
    )


@login_required
def update_cart_item(request, pk):
    if request.method != "POST":
        raise Http404
    customer = _customer_for(request)
    item = _owned_item(customer, pk)
    form = CartQuantityForm(request.POST, minimum_order_quantity=item.product.minimum_order_quantity)
    if form.is_valid():
        try:
            update_quantity(item=item, quantity=form.cleaned_data["quantity"])
        except ValidationError as error:
            messages.error(request, f"{item.product.name}: {_error_message(error)}")
        else:
            messages.success(request, f"{item.product.name} quantity updated.")
    else:
        messages.error(request, f"{item.product.name}: enter a valid positive quantity.")
    return redirect("shop-cart")


@login_required
def remove_cart_item(request, pk):
    if request.method != "POST":
        raise Http404
    customer = _customer_for(request)
    item = _owned_item(customer, pk)
    name = item.product.name
    item.delete()
    messages.success(request, f"{name} was removed from your cart.")
    return redirect("shop-cart")


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
