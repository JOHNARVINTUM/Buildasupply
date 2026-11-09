from django.urls import path

from . import views

urlpatterns = [
    path("checkout/", views.checkout_page, name="shop-checkout"),
    path("checkout/submit/", views.checkout_submit, name="shop-checkout-submit"),
    path("orders/", views.order_history, name="shop-orders"),
    path("orders/<uuid:pk>/", views.order_detail, name="shop-order-detail"),
    path("orders/<uuid:pk>/supplier-orders/<uuid:supplier_order_id>/confirm-receipt/", views.confirm_cod_receipt, name="shop-cod-receipt-confirm"),
    path("orders/<uuid:pk>/cancel-cod/", views.cancel_cod_order, name="shop-cod-cancel"),
    path("orders/<uuid:pk>/confirmation/", views.order_confirmation, name="shop-order-confirmation"),
]
