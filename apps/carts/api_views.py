from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.catalog.selectors import customer_catalog_queryset
from apps.catalog.models import Product
from .services import add_item,get_active_cart,update_quantity,validate_cart
def product_data(p,detail=False):
    data={"id":str(p.id),"name":p.name,"supplier":p.supplier.display_name,"supplier_id":str(p.supplier_id),"category":p.category.name if p.category else None,"price_minor":p.current_amount,"currency":p.current_currency,"unit":p.unit_of_measure,"minimum_order_quantity":p.minimum_order_quantity,"availability":"Low Stock" if p.inventory.available_quantity<=p.inventory.low_stock_threshold else "In Stock"}
    if detail:data.update(description=p.description,images=[{"url":i.file.url,"alt":i.alt_text} for i in p.images.filter(is_active=True)])
    return data
class CatalogProductsView(APIView):
    permission_classes=[AllowAny]
    def get(self,request):
        qs=customer_catalog_queryset()
        if q:=request.query_params.get("q"):qs=qs.filter(name__icontains=q)|qs.filter(description__icontains=q)|qs.filter(sku__icontains=q)
        for field in ("category","supplier"):
            if value:=request.query_params.get(field):qs=qs.filter(**{f"{field}_id":value})
        try:
            if request.query_params.get("min_price"):qs=qs.filter(current_amount__gte=int(request.query_params["min_price"]))
            if request.query_params.get("max_price"):qs=qs.filter(current_amount__lte=int(request.query_params["max_price"]))
            size=min(max(int(request.query_params.get("page_size",20)),1),50);page=int(request.query_params.get("page",1))
        except ValueError:return Response({"detail":"Invalid pagination or price filter."},status=400)
        ordering={"price_asc":"current_amount","price_desc":"-current_amount","newest":"-created_at","name":"name"}.get(request.query_params.get("sort"),"name")
        page_obj=Paginator(qs.order_by(ordering),size).get_page(page)
        return Response({"count":page_obj.paginator.count,"page":page_obj.number,"results":[product_data(p) for p in page_obj]})
class CatalogProductDetailView(APIView):
    permission_classes=[AllowAny]
    def get(self,request,pk):
        p=customer_catalog_queryset().filter(pk=pk).first()
        return Response({"detail":"Product unavailable."},status=404) if not p else Response(product_data(p,True))
class CartView(APIView):
    def get(self,request):
        if not hasattr(request.user,"customer_profile"):return Response({"detail":"Customer access required."},status=403)
        cart=get_active_cart(request.user.customer_profile);items=[];subtotal=0
        for item in cart.items.select_related("product__supplier"):
            line=item.quantity*item.displayed_price_minor;subtotal+=line;items.append({"id":item.id,"product":item.product.name,"supplier":item.product.supplier.display_name,"quantity":item.quantity,"unit_price_minor":item.displayed_price_minor,"currency":item.displayed_currency,"line_subtotal_minor":line})
        return Response({"id":cart.id,"items":items,"estimated_subtotal_minor":subtotal,"currency":cart.currency})
class CartItemsView(APIView):
    def post(self,request):
        if not hasattr(request.user,"customer_profile"):return Response({"detail":"Customer access required."},status=403)
        try:item=add_item(customer=request.user.customer_profile,product=Product.objects.get(pk=request.data["product_id"]),quantity=int(request.data["quantity"]))
        except (KeyError,ValueError,Product.DoesNotExist,ValidationError) as exc:return Response({"detail":str(exc)},status=400)
        return Response({"id":item.id},status=201)
class CartItemDetailView(APIView):
    def _item(self,request,pk):
        if not hasattr(request.user,"customer_profile"):return None
        return get_active_cart(request.user.customer_profile).items.select_related("product__supplier","product__inventory").filter(pk=pk).first()
    def patch(self,request,pk):
        item=self._item(request,pk)
        if not item:return Response({"detail":"Not found."},status=404)
        try:update_quantity(item=item,quantity=int(request.data["quantity"]))
        except (KeyError,ValueError,ValidationError) as exc:return Response({"detail":str(exc)},status=400)
        return Response({"id":item.id,"quantity":item.quantity})
    def delete(self,request,pk):
        item=self._item(request,pk)
        if not item:return Response({"detail":"Not found."},status=404)
        item.delete();return Response(status=204)
class CartValidationView(CartView):
    def post(self,request):
        if not hasattr(request.user,"customer_profile"):return Response({"detail":"Customer access required."},status=403)
        return Response(validate_cart(get_active_cart(request.user.customer_profile)))
