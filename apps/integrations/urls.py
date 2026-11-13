from django.urls import path

from .views import RealEstateOrderDeliveryStatusView


urlpatterns = [
    path(
        "realestate/orders/<str:order_number>/delivery-status/",
        RealEstateOrderDeliveryStatusView.as_view(),
        name="integration-realestate-order-delivery-status",
    ),
]
