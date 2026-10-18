from django.urls import path
from . import views
app_name = "accounts"
urlpatterns = [path("register/", views.customer_register, name="register"), path("supplier/register/", views.supplier_register, name="supplier-register"), path("registration-success/", views.registration_success, name="registration-success"), path("login/", views.login_view, name="login"), path("logout/", views.logout_view, name="logout"), path("profile/", views.profile, name="profile"), path("password-reset/", views.password_reset, name="password-reset"), path("password-reset/done/", views.password_reset_done, name="password-reset-done"), path("reset/<uidb64>/<token>/", views.password_reset_confirm, name="password-reset-confirm")]
