from django.urls import path
from . import views
urlpatterns=[path("",views.browse,name="shop-home"),path("browse/",views.browse,name="shop-browse"),path("products/<uuid:pk>/",views.product_detail,name="shop-product-detail"),path("cart/",views.cart_page,name="shop-cart"),path("checkout/",views.checkout_page,name="shop-checkout"),path("orders/",views.order_history,name="shop-orders"),path("payments/<uuid:pk>/",views.payment_status,name="shop-payment")]
