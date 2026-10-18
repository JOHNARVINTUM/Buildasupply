from django.urls import path
from . import views
urlpatterns=[path("",views.dashboard,name="supplier-home"),path("dashboard/",views.dashboard,name="supplier-dashboard"),path("products/",views.product_list,name="supplier-products"),path("wallet/",views.wallet_page,name="supplier-wallet")]
