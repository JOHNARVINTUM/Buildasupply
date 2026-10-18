from django.contrib.auth.backends import ModelBackend
from .models import User
class ActiveUserModelBackend(ModelBackend):
    def user_can_authenticate(self, user): return bool(user and user.account_status == "ACTIVE" and user.is_active)
    def get_user(self, user_id):
        # Return the account so AccountStatusMiddleware can invalidate a stale session.
        try: return User.objects.get(pk=user_id)
        except User.DoesNotExist: return None
