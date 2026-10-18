from django.urls import path
from .api_views import CatalogProductsView, CatalogProductDetailView, CartView, CartItemsView, CartItemDetailView, CartValidationView
urlpatterns=[path("catalog/products/",CatalogProductsView.as_view()),path("catalog/products/<uuid:pk>/",CatalogProductDetailView.as_view()),path("cart/",CartView.as_view()),path("cart/items/",CartItemsView.as_view()),path("cart/items/<int:pk>/",CartItemDetailView.as_view()),path("cart/validate/",CartValidationView.as_view())]
