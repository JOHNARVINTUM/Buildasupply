from django.urls import path
from .api_views import PayoutMethodsView,PayoutsView
urlpatterns=[path("supplier/payout-methods/",PayoutMethodsView.as_view()),path("supplier/payouts/",PayoutsView.as_view())]
