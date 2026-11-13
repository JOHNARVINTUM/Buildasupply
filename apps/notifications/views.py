from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from .models import Notification
@login_required
def center(request):
    role = request.user.primary_role
    layout, return_url, return_label = {
        "CUSTOMER": ("customers/layout.html", "shop-browse", "Browse supplies"),
        "STAFF_BUYER": ("customers/layout.html", "shop-browse", "Browse supplies"),
        "SUPPLIER": ("suppliers/layout.html", "supplier-dashboard", "Back to dashboard"),
        "SUPERADMIN": ("operations/layout.html", "operations-dashboard", "Back to dashboard"),
    }.get(role, ("customers/layout.html", "shop-browse", "Browse supplies"))
    intro = {
        "CUSTOMER": "Order progress, payment updates, and the details that keep your build moving.",
        "STAFF_BUYER": "Purchase, payment, and delivery updates for your supply orders.",
        "SUPPLIER": "Order progress, fulfillment updates, and the details that keep your business moving.",
        "SUPERADMIN": "Marketplace activity, payment updates, and the details that need your attention.",
    }.get(role, "Your latest account updates.")
    return render(request, "notifications/center.html", {
        "notifications": Notification.objects.filter(recipient=request.user).order_by("-created_at")[:50],
        "notification_layout": layout, "notification_intro": intro,
        "notification_return_url": return_url, "notification_return_label": return_label,
    })
