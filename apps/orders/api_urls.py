from django.urls import path
from .api_views import CheckoutView, CustomerOrdersView, CustomerOrderDetailView, SupplierOrdersView
urlpatterns=[path("checkout/",CheckoutView.as_view()),path("orders/",CustomerOrdersView.as_view()),path("orders/<uuid:pk>/",CustomerOrderDetailView.as_view()),path("supplier/orders/",SupplierOrdersView.as_view())]
