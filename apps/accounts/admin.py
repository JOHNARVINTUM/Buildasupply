from django.contrib import admin
from .models import User
@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "primary_role", "account_status", "is_staff")
    list_filter = ("primary_role", "account_status")
    search_fields = ("email",)
    readonly_fields = ("password", "last_login", "created_at", "updated_at")
