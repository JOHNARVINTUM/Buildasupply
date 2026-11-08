from django.urls import path
from . import views
urlpatterns=[path("",views.dashboard,name="supplier-home"),path("dashboard/",views.dashboard,name="supplier-dashboard"),path("products/",views.product_list,name="supplier-products"),path("products/create/",views.product_create,name="supplier-product-create"),path("products/<uuid:pk>/edit/",views.product_edit,name="supplier-product-edit"),path("products/<uuid:pk>/submit/",views.product_submit,name="supplier-product-submit"),path("wallet/",views.wallet_page,name="supplier-wallet")]
