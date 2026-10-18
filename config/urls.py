from django.contrib import admin
from django.urls import include, path
from .views import home

urlpatterns = [path("", home, name="home"), path("admin/", admin.site.urls), path("", include("apps.accounts.urls")), path("supplier/", include("apps.catalog.urls")), path("shop/", include("apps.carts.urls")), path("operations/",include("apps.operations.urls")), path("notifications/",include("apps.notifications.urls")), path("api/v1/", include("apps.accounts.api_urls")), path("api/v1/", include("apps.catalog.api_urls")), path("api/v1/", include("apps.inventory.api_urls")), path("api/v1/", include("apps.carts.api_urls")), path("api/v1/", include("apps.orders.api_urls")), path("api/v1/", include("apps.payments.api_urls")), path("api/v1/", include("apps.wallets.api_urls")), path("api/v1/", include("apps.payouts.api_urls")), path("api/v1/",include("apps.operations.api_urls")), path("api/v1/",include("apps.notifications.api_urls"))]
