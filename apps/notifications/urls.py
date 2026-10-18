from django.urls import path
from . import views
urlpatterns=[path("",views.center,name="notifications-center")]
