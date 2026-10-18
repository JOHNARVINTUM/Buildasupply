from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Notification,NotificationPreference
class NotificationsView(APIView):
    def get(self,request):
        qs=Notification.objects.filter(recipient=request.user).order_by("-created_at")
        if request.query_params.get("unread")=="true":qs=qs.filter(read_at__isnull=True)
        return Response([{"id":str(n.id),"title":n.title,"body":n.body,"event_type":n.event_type,"read":bool(n.read_at),"link":n.link} for n in qs[:50]])
class UnreadView(APIView):
    def get(self,request):return Response({"count":Notification.objects.filter(recipient=request.user,read_at__isnull=True).count()})
class ReadView(APIView):
    def post(self,request,pk):
        n=Notification.objects.filter(pk=pk,recipient=request.user).first()
        if not n:return Response({"detail":"Not found."},status=404)
        n.read_at=timezone.now();n.save(update_fields=["read_at"]);return Response({"read":True})
class ReadAllView(APIView):
    def post(self,request):Notification.objects.filter(recipient=request.user,read_at__isnull=True).update(read_at=timezone.now());return Response(status=204)
class PreferencesView(APIView):
    def get(self,request):return Response([{"category":p.category,"in_app":p.in_app,"email":p.email} for p in request.user.notification_preferences.all()])
    def patch(self,request):
        p,_=NotificationPreference.objects.update_or_create(recipient=request.user,category=request.data["category"],defaults={"in_app":bool(request.data.get("in_app",True)),"email":bool(request.data.get("email",False))});return Response({"category":p.category,"in_app":p.in_app,"email":p.email})
