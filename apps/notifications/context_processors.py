def notification_summary(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {"notification_unread_count": 0}
    return {"notification_unread_count": request.user.notifications.filter(read_at__isnull=True).count()}
