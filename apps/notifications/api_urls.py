from django.urls import path
from .api_views import NotificationsView,UnreadView,ReadView,ReadAllView,PreferencesView
urlpatterns=[path("notifications/",NotificationsView.as_view()),path("notifications/unread-count/",UnreadView.as_view()),path("notifications/<uuid:pk>/read/",ReadView.as_view()),path("notifications/read-all/",ReadAllView.as_view()),path("notification-preferences/",PreferencesView.as_view())]
