from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from .models import Notification
@login_required
def center(request): return render(request,"notifications/center.html",{"notifications":Notification.objects.filter(recipient=request.user).order_by("-created_at")[:50]})
