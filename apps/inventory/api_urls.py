from django.urls import path
from .api_views import InventoryDetailView, InventoryActionView, InventoryMovementView
urlpatterns=[path("inventory/<int:pk>/",InventoryDetailView.as_view()),path("inventory/<int:pk>/adjust/",InventoryActionView.as_view()),path("inventory/<int:pk>/movements/",InventoryMovementView.as_view())]
