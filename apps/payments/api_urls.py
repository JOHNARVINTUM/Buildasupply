from django.urls import path
from .api_views import OrderPaymentView, PaymentDetailView, PaymentWebhookView
urlpatterns=[path("orders/<uuid:order_id>/payment/",OrderPaymentView.as_view()),path("payments/<uuid:pk>/",PaymentDetailView.as_view()),path("payments/webhooks/<str:provider>/",PaymentWebhookView.as_view())]
