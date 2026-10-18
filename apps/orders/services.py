import hashlib
from collections import defaultdict
from datetime import timedelta
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from apps.audit.services import log_action
from apps.catalog.services import current_price_for, is_product_purchasable
from apps.inventory.models import Inventory, InventoryMovement, InventoryReservation
from apps.memberships.services import get_active_membership, get_applicable_benefits
from .models import CheckoutIdempotency, Delivery, MasterOrder, OrderFinancialLine, OrderItem, SupplierOrder
class CheckoutFailure(ValidationError): pass
def _fingerprint(cart):
    material="|".join(f"{x.product_id}:{x.quantity}:{x.displayed_price_minor}:{x.displayed_currency}" for x in cart.items.order_by("product_id"))
    return hashlib.sha256(material.encode()).hexdigest()
def _address_snapshot(customer):
    address=customer.addresses.filter(is_default=True).first() or customer.addresses.first()
    if not address: raise CheckoutFailure({"code":"DELIVERY_ADDRESS_REQUIRED"})
    return {key:getattr(address,key) for key in ("recipient_name","phone","address_line1","address_line2","barangay","city","province","postal_code","country")}
@transaction.atomic
def checkout(*,customer,idempotency_key):
    if not idempotency_key: raise CheckoutFailure({"code":"IDEMPOTENCY_REQUIRED"})
    from apps.carts.models import Cart
    prior=CheckoutIdempotency.objects.select_related("master_order").filter(customer=customer,key=idempotency_key).first()
    if prior and prior.master_order:return {"success":True,"master_order_id":str(prior.master_order_id),"order_number":prior.master_order.order_number,"idempotent":True}
    cart=Cart.objects.select_for_update().filter(customer=customer,status="ACTIVE",currency="PHP").first()
    if not cart or not cart.items.exists(): raise CheckoutFailure({"code":"CART_EMPTY"})
    fingerprint=_fingerprint(cart)
    prior=CheckoutIdempotency.objects.select_related("master_order").filter(customer=customer,key=idempotency_key).first()
    if prior:
        if prior.fingerprint != fingerprint: raise CheckoutFailure({"code":"IDEMPOTENCY_KEY_REUSED"})
    token=CheckoutIdempotency.objects.create(customer=customer,key=idempotency_key,fingerprint=fingerprint)
    cart_items=list(cart.items.select_related("product__supplier").order_by("product_id"))
    inventory_map={i.product_id:i for i in Inventory.objects.select_for_update().select_related("product__supplier").filter(product_id__in=[x.product_id for x in cart_items]).order_by("product_id")}
    validated=[]; errors=[]
    for item in cart_items:
        inventory=inventory_map.get(item.product_id); product=item.product; price=current_price_for(product)
        code=None
        if not inventory or not is_product_purchasable(product): code="PRODUCT_UNAVAILABLE"
        elif product.supplier.approval_status!="APPROVED" or product.supplier.operational_status!="ACTIVE":code="SUPPLIER_UNAVAILABLE"
        elif not price:code="PRODUCT_UNAVAILABLE"
        elif price.currency!=item.displayed_currency:code="CURRENCY_MISMATCH"
        elif price.amount_minor!=item.displayed_price_minor:code="PRICE_CHANGED"
        elif item.quantity<product.minimum_order_quantity:code="MOQ_NOT_MET"
        elif item.quantity>inventory.available_quantity:code="INSUFFICIENT_STOCK"
        if code:errors.append({"product":product.name,"code":code,"previous_price":item.displayed_price_minor,"current_price":price.amount_minor if price else None})
        else:validated.append((item,product,inventory,price))
    if errors: raise CheckoutFailure({"code":"CHECKOUT_VALIDATION_FAILED","errors":errors})
    address=_address_snapshot(customer); subtotal=sum(item.quantity*price.amount_minor for item,_,_,price in validated); membership=get_active_membership(customer) or {}
    order_number=f"BS-{timezone.now():%Y%m%d}-{token.pk:06d}"
    master=MasterOrder.objects.create(order_number=order_number,customer=customer,currency="PHP",subtotal_minor=subtotal,total_minor=subtotal,membership_snapshot=membership)
    by_supplier=defaultdict(list)
    for row in validated:by_supplier[row[1].supplier_id].append(row)
    supplier_orders=[]
    for supplier_id,rows in by_supplier.items():
        supplier=rows[0][1].supplier; amount=sum(item.quantity*price.amount_minor for item,_,_,price in rows)
        so=SupplierOrder.objects.create(master_order=master,supplier=supplier,supplier_name_snapshot=supplier.display_name,subtotal_minor=amount,total_minor=amount,currency="PHP");supplier_orders.append(so)
        for item,product,inventory,price in rows:
            line=item.quantity*price.amount_minor
            OrderItem.objects.create(supplier_order=so,product=product,product_id_snapshot=product.id,product_name=product.name,sku=product.sku,unit_of_measure=product.unit_of_measure,supplier_id_snapshot=supplier.id,supplier_name_snapshot=supplier.display_name,unit_price_minor=price.amount_minor,quantity=item.quantity,line_total_minor=line,currency=price.currency)
            inventory.available_quantity-=item.quantity;inventory.reserved_quantity+=item.quantity;inventory.status="ACTIVE" if inventory.available_quantity else "OUT_OF_STOCK";inventory.save(update_fields=["available_quantity","reserved_quantity","status","updated_at"])
            InventoryReservation.objects.create(inventory=inventory,quantity=item.quantity,supplier_order=so,expires_at=timezone.now()+timedelta(minutes=30))
            InventoryMovement.objects.create(inventory=inventory,movement_type="RESERVATION",quantity_delta=-item.quantity,reason=f"Checkout {order_number}",actor=customer.user,reference_type="orders.SupplierOrder",reference_id=so.id)
        Delivery.objects.create(supplier_order=so,address_snapshot=address)
        OrderFinancialLine.objects.create(master_order=master,supplier_order=so,line_type="SUBTOTAL",source="PRODUCT_PRICE",description="Product subtotal",amount_minor=amount,currency="PHP",calculation_basis={"items":len(rows)})
    OrderFinancialLine.objects.create(master_order=master,line_type="TOTAL",source="CHECKOUT",description="Order total",amount_minor=subtotal,currency="PHP",calculation_basis={"subtotal":subtotal,"discount":0,"tax":0,"platform_fee":0,"delivery_fee":0})
    cart.status="CHECKED_OUT";cart.save(update_fields=["status","updated_at"]);token.master_order=master;token.save(update_fields=["master_order"])
    log_action(actor=customer.user,action="CHECKOUT_COMPLETED",target=master,after={"order_number":order_number,"total_minor":subtotal})
    return {"success":True,"master_order_id":str(master.id),"order_number":order_number,"supplier_orders":[str(x.id) for x in supplier_orders],"total_minor":subtotal,"currency":"PHP"}
@transaction.atomic
def release_reservation(*,reservation,actor,reason):
    reservation=InventoryReservation.objects.select_for_update().select_related("inventory").get(pk=reservation.pk)
    if reservation.status!="ACTIVE":raise ValidationError("Reservation is not active.")
    inv=reservation.inventory;inv.available_quantity+=reservation.quantity;inv.reserved_quantity-=reservation.quantity;inv.status="ACTIVE";inv.save(update_fields=["available_quantity","reserved_quantity","status","updated_at"])
    reservation.status="RELEASED";reservation.save(update_fields=["status","updated_at"]);InventoryMovement.objects.create(inventory=inv,movement_type="RESERVATION_RELEASE",quantity_delta=reservation.quantity,reason=reason,actor=actor,reference_type="orders.SupplierOrder",reference_id=reservation.supplier_order_id)
def transition_supplier_order(*,supplier_order,actor,next_status):
    transitions={"PENDING_PAYMENT":{"PAID"},"PAID":{"PENDING_SUPPLIER"},"PENDING_SUPPLIER":{"CONFIRMED"},"CONFIRMED":{"PREPARING"},"PREPARING":{"READY_FOR_DELIVERY"},"READY_FOR_DELIVERY":{"SHIPPED"},"SHIPPED":{"DELIVERED"},"DELIVERED":{"COMPLETED"}}
    if actor.primary_role != "SUPERADMIN" and not actor.supplier_memberships.filter(supplier=supplier_order.supplier,status="ACTIVE").exists():raise ValidationError("Order access denied.")
    if next_status not in transitions.get(supplier_order.status,set()):raise ValidationError("Invalid order transition.")
    supplier_order.status=next_status;supplier_order.save(update_fields=["status"]);log_action(actor=actor,action="SUPPLIER_ORDER_TRANSITION",target=supplier_order,after={"status":next_status})
