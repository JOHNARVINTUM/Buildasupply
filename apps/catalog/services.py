from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.db.models import Q
from apps.audit.services import log_action
from apps.inventory.models import Inventory
from .models import Category, Product, ProductPrice
def _category_valid(category): return bool(category and category.is_active)
def is_product_purchasable(product):
    inventory = getattr(product, "inventory", None)
    return bool(product.supplier.approval_status == "APPROVED" and product.supplier.operational_status == "ACTIVE" and product.status == "APPROVED" and product.public_availability and inventory and inventory.status == "ACTIVE" and inventory.available_quantity > 0 and current_price_for(product))
def current_price_for(product):
    now=timezone.now()
    return product.prices.filter(is_active=True, starts_at__lte=now).filter(Q(ends_at__isnull=True)|Q(ends_at__gt=now)).order_by("-starts_at").first()
@transaction.atomic
def create_product(*, supplier, actor, name, sku, category, description, unit_of_measure, minimum_order_quantity, amount_minor, currency="PHP"):
    product=Product.objects.create(supplier=supplier, name=name, sku=sku, category=category, description=description, unit_of_measure=unit_of_measure, minimum_order_quantity=minimum_order_quantity)
    ProductPrice.objects.create(product=product, amount_minor=amount_minor, currency=currency, starts_at=timezone.now())
    Inventory.objects.create(product=product)
    log_action(actor=actor, action="PRODUCT_CREATED", target=product); return product
@transaction.atomic
def submit_for_review(*, product, actor):
    if product.status not in {"DRAFT", "REJECTED"}: raise ValidationError("Only draft or rejected products can be submitted.")
    if not _category_valid(product.category): raise ValidationError("An active category is required for review.")
    before={"status": product.status}; product.status="PENDING_REVIEW"; product.moderation_reason=""; product.save(update_fields=["status", "moderation_reason", "updated_at"])
    log_action(actor=actor, action="PRODUCT_SUBMITTED", target=product, before=before, after={"status": product.status})
@transaction.atomic
def moderate_product(*, product, actor, approve, reason=""):
    if product.status != "PENDING_REVIEW": raise ValidationError("Only pending products may be moderated.")
    if not approve and not reason: raise ValidationError("A rejection reason is required.")
    before={"status": product.status}; product.status="APPROVED" if approve else "REJECTED"; product.moderation_reason=reason; product.reviewed_by=actor; product.reviewed_at=timezone.now(); product.save(update_fields=["status", "moderation_reason", "reviewed_by", "reviewed_at", "updated_at"])
    log_action(actor=actor, action="PRODUCT_APPROVED" if approve else "PRODUCT_REJECTED", target=product, before=before, after={"status": product.status})
@transaction.atomic
def archive_product(*, product, actor):
    if product.status == "ARCHIVED": return
    before={"status": product.status}; product.status="ARCHIVED"; product.public_availability=False; product.save(update_fields=["status", "public_availability", "updated_at"])
    log_action(actor=actor, action="PRODUCT_ARCHIVED", target=product, before=before, after={"status":"ARCHIVED"})
@transaction.atomic
def update_product(*, product, actor, **changes):
    allowed={"name","sku","description","category","unit_of_measure","minimum_order_quantity","public_availability"}
    before={key:getattr(product,key) if key != "category" else product.category_id for key in changes if key in allowed}
    for key,value in changes.items():
        if key in allowed: setattr(product,key,value)
    if product.status == "APPROVED" and any(key in changes for key in {"name","sku","description","category","unit_of_measure","minimum_order_quantity"}):
        product.status="DRAFT"; product.reviewed_by=None; product.reviewed_at=None
    product.full_clean(); product.save()
    log_action(actor=actor,action="PRODUCT_UPDATED",target=product,before=before,after={"status":product.status})
@transaction.atomic
def transition_supplier(*, supplier, actor, status, reason=""):
    allowed={"PENDING_REVIEW":{"APPROVED","REJECTED","SUSPENDED"},"APPROVED":{"SUSPENDED"},"SUSPENDED":{"APPROVED"},"REJECTED":set()}
    if status not in allowed[supplier.approval_status]: raise ValidationError("Invalid supplier status transition.")
    before={"approval_status":supplier.approval_status}; supplier.approval_status=status; supplier.review_reason=reason; supplier.save(update_fields=["approval_status","review_reason","updated_at"])
    log_action(actor=actor, action=f"SUPPLIER_{status}", target=supplier, before=before, after={"approval_status":status})
    if status=="APPROVED":
        from apps.notifications.services import emit
        emit("supplier.approved",supplier,{"recipient_ids":[str(x.user_id) for x in supplier.staff_memberships.filter(status="ACTIVE")],"link":"/supplier/dashboard/"})
