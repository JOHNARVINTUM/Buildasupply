from django.urls import path
from .api_views import ProductListCreateView, ProductDetailView, ProductActionView, CategoryListView, SupplierActionView, SupplierMeView
urlpatterns=[path("products/", ProductListCreateView.as_view()),path("products/<uuid:pk>/", ProductDetailView.as_view()),path("products/<uuid:pk>/<str:action>/", ProductActionView.as_view()),path("categories/", CategoryListView.as_view()),path("suppliers/me/",SupplierMeView.as_view()),path("admin/suppliers/<uuid:pk>/<str:action>/", SupplierActionView.as_view())]
