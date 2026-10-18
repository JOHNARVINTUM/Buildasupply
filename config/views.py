from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect, render


def home(request):
    """Provide the public entry point and server-side role routing."""
    if not request.user.is_authenticated:
        return render(request, "home.html")

    destinations = {
        "CUSTOMER": "shop-home",
        "SUPPLIER": "supplier-home",
        "SUPERADMIN": "operations-home",
    }
    destination = destinations.get(request.user.primary_role)
    if destination:
        return redirect(destination)

    # A malformed or unsupported role must not inherit access from a session.
    logout(request)
    messages.error(request, "Your account role is not recognized. Please contact support.")
    return redirect("accounts:login")
