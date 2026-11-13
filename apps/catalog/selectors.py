from django.db.models import OuterRef, Prefetch, Q, Subquery
from django.utils import timezone
from .models import Product, ProductImage, ProductPrice
def customer_catalog_queryset():
    now=timezone.now()
    current_price=ProductPrice.objects.filter(product_id=OuterRef("pk"),is_active=True,starts_at__lte=now).filter(Q(ends_at__isnull=True)|Q(ends_at__gt=now)).order_by("-starts_at")
    active_images=ProductImage.objects.filter(is_active=True).order_by("-is_primary","display_order","pk")
    return Product.objects.filter(supplier__approval_status="APPROVED",supplier__operational_status="ACTIVE",status="APPROVED",public_availability=True,inventory__status="ACTIVE",inventory__available_quantity__gt=0).select_related("supplier","category","inventory").prefetch_related(Prefetch("images",queryset=active_images,to_attr="active_images")).annotate(current_amount=Subquery(current_price.values("amount_minor")[:1]),current_currency=Subquery(current_price.values("currency")[:1])).filter(current_amount__isnull=False)
