from django.urls import path
from . import views
urlpatterns=[path("",views.browse,name="shop-home"),path("browse/",views.browse,name="shop-browse"),path("products/<uuid:pk>/",views.product_detail,name="shop-product-detail"),path("products/<uuid:pk>/add/",views.add_to_cart,name="shop-add-to-cart"),path("cart/",views.cart_page,name="shop-cart"),path("cart/items/<int:pk>/update/",views.update_cart_item,name="shop-cart-item-update"),path("cart/items/<int:pk>/remove/",views.remove_cart_item,name="shop-cart-item-remove")]
