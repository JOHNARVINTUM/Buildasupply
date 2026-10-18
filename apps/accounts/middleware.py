from django.contrib.auth import logout


class AccountStatusMiddleware:
    """Reject stale authenticated sessions after an account is suspended or deactivated."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and request.user.account_status != "ACTIVE":
            logout(request)
        return self.get_response(request)
