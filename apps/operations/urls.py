from django.urls import path
from . import views
urlpatterns=[path("",views.dashboard,name="operations-home"),path("dashboard/",views.dashboard,name="operations-dashboard"),path("audit/",views.audit_view,name="operations-audit")]
