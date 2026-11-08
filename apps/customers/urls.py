from django.urls import path

from . import views

app_name = "customers"

urlpatterns = [
    path("addresses/", views.address_list, name="address-list"),
    path("addresses/new/", views.address_create, name="address-create"),
    path("addresses/<int:pk>/edit/", views.address_edit, name="address-edit"),
    path("addresses/<int:pk>/delete/", views.address_delete, name="address-delete"),
    path("addresses/<int:pk>/default/", views.address_set_default, name="address-set-default"),
]
