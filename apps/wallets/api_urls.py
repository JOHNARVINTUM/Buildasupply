from django.urls import path
from .api_views import WalletView,TransactionsView
urlpatterns=[path("supplier/wallet/",WalletView.as_view()),path("supplier/wallet/transactions/",TransactionsView.as_view())]
