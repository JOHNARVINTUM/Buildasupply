from django.urls import path

from . import views

urlpatterns = [
    path("orders/<uuid:order_id>/payment/", views.payment_select, name="shop-payment-select"),
    path("orders/<uuid:order_id>/payment/pesoway/", views.pesoway_start, name="shop-pesoway-start"),
    path("orders/<uuid:order_id>/cash-on-delivery/", views.cod_select, name="shop-cod-select"),
    path("payments/<uuid:pk>/instructions/", views.payment_instructions, name="shop-payment-instructions"),
    path("payments/<uuid:pk>/", views.payment_status, name="shop-payment"),
]
