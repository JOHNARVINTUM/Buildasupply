from rest_framework.response import Response
from rest_framework.views import APIView
from .permissions import IsActiveAccount, can_manage_catalog
from apps.suppliers.models import Supplier
class MeView(APIView):
    permission_classes = [IsActiveAccount]
    def get(self, request): return Response({"id": str(request.user.id), "email": request.user.email, "role": request.user.primary_role})
class SupplierScopeProbeView(APIView):
    permission_classes = [IsActiveAccount]
    def get(self, request, supplier_id):
        supplier = Supplier.objects.filter(id=supplier_id).first()
        if not supplier or not can_manage_catalog(request.user, supplier): return Response({"detail": "Not found."}, status=404)
        return Response({"supplier_id": str(supplier.id), "access": "catalog"})
