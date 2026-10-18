from django.contrib.auth.base_user import BaseUserManager
class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra):
        if not email: raise ValueError("Email is required")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user
    def create_superuser(self, email, password, **extra):
        extra.update(primary_role="SUPERADMIN", account_status="ACTIVE", is_staff=True, is_superuser=True)
        return self.create_user(email, password, **extra)
