from django.urls import path

from . import supplier_views


urlpatterns = [
    path("orders/", supplier_views.cod_order_dashboard, name="supplier-cod-orders"),
    path("orders/<uuid:pk>/", supplier_views.cod_order_detail, name="supplier-cod-order-detail"),
    path("orders/<uuid:pk>/accept/", supplier_views.accept_cod_order, name="supplier-cod-order-accept"),
    path("orders/<uuid:pk>/prepare/", supplier_views.prepare_order, name="supplier-cod-order-prepare"),
    path("orders/<uuid:pk>/ready/", supplier_views.ready_order, name="supplier-cod-order-ready"),
    path("orders/<uuid:pk>/dispatch/", supplier_views.dispatch_order, name="supplier-cod-order-dispatch"),
    path("orders/<uuid:pk>/deliver/", supplier_views.deliver_order, name="supplier-cod-order-deliver"),
    path("orders/<uuid:pk>/collect/", supplier_views.record_collection, name="supplier-cod-order-collect"),
    path("orders/<uuid:pk>/exception/", supplier_views.report_exception, name="supplier-cod-order-exception"),
]
