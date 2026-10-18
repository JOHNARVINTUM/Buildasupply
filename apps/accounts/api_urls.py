from django.urls import path
from .api_views import MeView, SupplierScopeProbeView
urlpatterns = [path("me/", MeView.as_view()), path("suppliers/<uuid:supplier_id>/scope/", SupplierScopeProbeView.as_view())]
