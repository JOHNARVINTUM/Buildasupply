from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from .models import Notification
from .services import emit,process
User=get_user_model()
class NotificationTests(TestCase):
    def test_event_creates_one_private_in_app_notification(self):
        a=User.objects.create_user("a@notice.com","Strongpass123!");b=User.objects.create_user("b@notice.com","Strongpass123!")
        class Target: pk=None
        Target._meta=type("M",(),{"label":"test.Target"})
        event=emit("payment.succeeded",Target(),{"recipient_ids":[str(a.id)],"order_number":"BS-1"});process(event.id)
        self.assertEqual(Notification.objects.filter(recipient=a).count(),1)
        client=APIClient();client.force_authenticate(b);note=Notification.objects.get(recipient=a)
        self.assertEqual(client.post(f"/api/v1/notifications/{note.id}/read/").status_code,404)
