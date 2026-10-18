from dataclasses import dataclass
from django.core.exceptions import ValidationError
from django.db import transaction
from apps.catalog.services import current_price_for, is_product_purchasable
from apps.memberships.services import get_active_membership, get_applicable_benefits
from .models import Cart, CartItem
def get_active_cart(customer): return Cart.objects.get_or_create(customer=customer,currency="PHP",status="ACTIVE")[0]
def _validate(product,quantity):
    if not is_product_purchasable(product): raise ValidationError("PRODUCT_UNAVAILABLE")
    if quantity <= 0: raise ValidationError("Quantity must be positive.")
    if quantity < product.minimum_order_quantity: raise ValidationError("MOQ_NOT_MET")
    if quantity > product.inventory.available_quantity: raise ValidationError("INSUFFICIENT_STOCK")
@transaction.atomic
def add_item(*,customer,product,quantity):
    product=type(product).objects.select_related("supplier","inventory").prefetch_related("prices").get(pk=product.pk);_validate(product,quantity);price=current_price_for(product);cart=get_active_cart(customer)
    item,created=CartItem.objects.get_or_create(cart=cart,product=product,defaults={"quantity":quantity,"displayed_price_minor":price.amount_minor,"displayed_currency":price.currency})
    if not created:item.quantity=quantity;item.displayed_price_minor=price.amount_minor;item.displayed_currency=price.currency;item.save()
    return item
@transaction.atomic
def update_quantity(*,item,quantity): _validate(item.product,quantity);item.quantity=quantity;item.save(update_fields=["quantity","updated_at"]);return item
def validate_cart(cart):
    result=[];valid=True
    for item in cart.items.select_related("product__supplier","product__inventory").prefetch_related("product__prices"):
        p=item.product;reason=None;price=current_price_for(p)
        if p.status=="ARCHIVED":reason="PRODUCT_ARCHIVED"
        elif not p.supplier.approval_status=="APPROVED" or p.supplier.operational_status!="ACTIVE":reason="SUPPLIER_UNAVAILABLE"
        elif not is_product_purchasable(p):reason="PRODUCT_UNAVAILABLE" if p.inventory.available_quantity else "OUT_OF_STOCK"
        elif not price:reason="PRODUCT_UNAVAILABLE"
        elif price.currency!=item.displayed_currency:reason="CURRENCY_CHANGED"
        elif price.amount_minor!=item.displayed_price_minor:reason="PRICE_CHANGED"
        elif item.quantity< p.minimum_order_quantity:reason="MOQ_NOT_MET"
        elif item.quantity>p.inventory.available_quantity:reason="INSUFFICIENT_STOCK"
        benefits=get_applicable_benefits(cart.customer,p)
        entry={"item_id":item.id,"product":p.name,"valid":not reason,"reason":reason,"current_price_minor":price.amount_minor if price else None,"currency":price.currency if price else None,"benefits":benefits}
        valid &= not bool(reason);result.append(entry)
    return {"valid":valid,"items":result,"membership":get_active_membership(cart.customer)}
