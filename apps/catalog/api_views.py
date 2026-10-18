from django.core.exceptions import ValidationError
from django.db.models import Q
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.accounts.permissions import IsActiveAccount, can_manage_catalog
from apps.suppliers.models import Supplier
from .models import Category, Product
from .services import archive_product, create_product, moderate_product, submit_for_review, transition_supplier, update_product
def supplier_for(user): return user.supplier_memberships.filter(status="ACTIVE").select_related("supplier").first()
class ProductListCreateView(APIView):
    permission_classes=[IsActiveAccount]
    def get(self, request):
        qs=Product.objects.select_related("supplier","category","inventory").order_by("-updated_at")
        if request.user.primary_role != "SUPERADMIN":
            membership=supplier_for(request.user)
            if not membership: return Response({"detail":"Not found."},status=404)
            qs=qs.filter(supplier=membership.supplier)
        for field in ("status","category","supplier"):
            if request.query_params.get(field): qs=qs.filter(**{field:request.query_params[field]})
        if request.query_params.get("search"): qs=qs.filter(Q(name__icontains=request.query_params["search"])|Q(sku__icontains=request.query_params["search"]))
        return Response([{"id":str(p.id),"name":p.name,"sku":p.sku,"status":p.status,"stock":p.inventory.available_quantity} for p in qs[:100]])
    def post(self, request):
        membership=supplier_for(request.user)
        if not membership or not can_manage_catalog(request.user,membership.supplier): return Response({"detail":"Not found."},status=404)
        try:
            category=Category.objects.get(pk=request.data.get("category")); p=create_product(supplier=membership.supplier,actor=request.user,category=category,name=request.data["name"],sku=request.data["sku"],description=request.data.get("description",""),unit_of_measure=request.data["unit_of_measure"],minimum_order_quantity=int(request.data.get("minimum_order_quantity",1)),amount_minor=int(request.data["amount_minor"])); return Response({"id":str(p.id),"status":p.status},status=201)
        except (KeyError,ValueError,Category.DoesNotExist,ValidationError) as exc: return Response({"detail":str(exc)},status=400)
class ProductDetailView(APIView):
    permission_classes=[IsActiveAccount]
    def get_object(self, request, pk):
        p=Product.objects.select_related("supplier","inventory").filter(pk=pk).first()
        if not p or (request.user.primary_role != "SUPERADMIN" and not can_manage_catalog(request.user,p.supplier)): return None
        return p
    def get(self,request,pk):
        p=self.get_object(request,pk)
        return Response({"detail":"Not found."},status=404) if not p else Response({"id":str(p.id),"name":p.name,"status":p.status,"stock":p.inventory.available_quantity})
    def patch(self,request,pk):
        p=self.get_object(request,pk)
        if not p:return Response({"detail":"Not found."},status=404)
        try:
            changes={key:value for key,value in request.data.items() if key in {"name","sku","description","unit_of_measure","minimum_order_quantity","public_availability"}}
            if "category" in request.data: changes["category"]=Category.objects.get(pk=request.data["category"])
            update_product(product=p,actor=request.user,**changes)
        except (Category.DoesNotExist,ValidationError) as exc:return Response({"detail":str(exc)},status=400)
        return Response({"id":str(p.id),"status":p.status})
class ProductActionView(ProductDetailView):
    def post(self,request,pk,action):
        p=self.get_object(request,pk)
        if not p:return Response({"detail":"Not found."},status=404)
        try:
            if action == "submit" and can_manage_catalog(request.user,p.supplier): submit_for_review(product=p,actor=request.user)
            elif action in {"approve","reject"} and request.user.primary_role=="SUPERADMIN": moderate_product(product=p,actor=request.user,approve=action=="approve",reason=request.data.get("reason",""))
            elif action == "archive" and can_manage_catalog(request.user,p.supplier): archive_product(product=p,actor=request.user)
            else:return Response({"detail":"Not found."},status=404)
        except ValidationError as exc:return Response({"detail":str(exc)},status=400)
        return Response({"status":p.status})
class CategoryListView(APIView):
    permission_classes=[IsActiveAccount]
    def get(self,request): return Response([{"id":str(c.id),"name":c.name,"slug":c.slug} for c in Category.objects.filter(is_active=True).order_by("display_order")])
    def post(self,request):
        if request.user.primary_role!="SUPERADMIN":return Response({"detail":"Not found."},status=404)
        try:
            parent=Category.objects.get(pk=request.data["parent"]) if request.data.get("parent") else None
            category=Category(name=request.data["name"],slug=request.data["slug"],parent=parent,description=request.data.get("description",""),display_order=int(request.data.get("display_order",0))); category.full_clean(); category.save()
        except (KeyError,ValueError,Category.DoesNotExist,ValidationError) as exc:return Response({"detail":str(exc)},status=400)
        return Response({"id":str(category.id)},status=201)
class SupplierMeView(APIView):
    permission_classes=[IsActiveAccount]
    def get(self,request):
        membership=supplier_for(request.user)
        if not membership:return Response({"detail":"Not found."},status=404)
        s=membership.supplier;return Response({"id":str(s.id),"legal_name":s.legal_name,"display_name":s.display_name,"email":s.email,"phone":s.phone,"approval_status":s.approval_status})
    def patch(self,request):
        membership=supplier_for(request.user)
        if not membership or not can_manage_catalog(request.user,membership.supplier):return Response({"detail":"Not found."},status=404)
        s=membership.supplier
        for field in {"legal_name","display_name","email","phone"}:
            if field in request.data:setattr(s,field,request.data[field])
        s.full_clean();s.save();return Response({"id":str(s.id),"display_name":s.display_name})
class SupplierActionView(APIView):
    permission_classes=[IsActiveAccount]
    def post(self,request,pk,action):
        if request.user.primary_role!="SUPERADMIN":return Response({"detail":"Not found."},status=404)
        supplier=Supplier.objects.filter(pk=pk).first()
        if not supplier:return Response({"detail":"Not found."},status=404)
        try: transition_supplier(supplier=supplier,actor=request.user,status={"approve":"APPROVED","reject":"REJECTED","suspend":"SUSPENDED","reinstate":"APPROVED"}[action],reason=request.data.get("reason",""))
        except (KeyError,ValidationError) as exc:return Response({"detail":str(exc)},status=400)
        return Response({"status":supplier.approval_status})
