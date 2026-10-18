from django.urls import path
from .api_views import DashboardView,AdminCollectionView,ConfigurationView,SupplierActionView
urlpatterns=[path("admin/dashboard/",DashboardView.as_view()),path("admin/configuration/",ConfigurationView.as_view()),path("admin/suppliers/<uuid:pk>/<str:action>/",SupplierActionView.as_view()),path("admin/<str:resource>/",AdminCollectionView.as_view())]
