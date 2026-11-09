from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from .models import Notification
from .models import DomainEvent, NotificationPreference
from .services import emit,process, supplier_recipient_ids, superadmin_recipient_ids
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

    def test_preferences_are_respected_and_processing_is_idempotent(self):
        user=User.objects.create_user("preference@notice.com","Strongpass123!")
        NotificationPreference.objects.create(recipient=user,category="order",in_app=False)
        class Target: pk=None
        Target._meta=type("M",(),{"label":"test.Target"})
        event=emit("order.created",Target(),{"recipient_ids":[str(user.id)],"order_number":"BS-2"})
        process(event.id);process(event.id)
        self.assertFalse(Notification.objects.filter(recipient=user).exists())
        event.refresh_from_db();self.assertEqual(event.status,"PROCESSED")

    def test_active_supplier_and_superadmin_recipient_resolution(self):
        from apps.accounts.services import register_supplier
        admin=User.objects.create_superuser("ops-notice@example.com","Strongpass123!")
        suspended=User.objects.create_superuser("suspended-notice@example.com","Strongpass123!")
        suspended.account_status="SUSPENDED";suspended.save()
        owner,supplier=register_supplier(email="supplier-notice@example.com",password1="Strongpass123!",full_name="Owner",phone="1",legal_name="Notification Supply Legal",display_name="Notification Supply",business_phone="1")
        self.assertEqual(supplier_recipient_ids(supplier),[str(owner.id)])
        self.assertIn(str(admin.id),superadmin_recipient_ids())
        self.assertNotIn(str(suspended.id),superadmin_recipient_ids())
