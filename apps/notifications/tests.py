from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from .models import Notification
from .models import DomainEvent, NotificationPreference
from .services import emit,process, supplier_recipient_ids, superadmin_recipient_ids
User=get_user_model()
class NotificationTests(TestCase):
    def test_role_notification_pages_share_cards_and_keep_notifications_private(self):
        from apps.accounts.services import register_customer, register_supplier
        from django.utils import timezone
        customer=register_customer(email="design-customer@example.com",password1="Strongpass123!",full_name="Customer",phone="1")
        owner,_=register_supplier(email="design-supplier@example.com",password1="Strongpass123!",full_name="Owner",phone="1",legal_name="Design Legal",display_name="Design Supplies",business_phone="1")
        admin=User.objects.create_superuser("design-admin@example.com","Strongpass123!")
        for user,workspace in ((customer,"customer"),(owner,"supplier"),(admin,"operations")):
            with self.subTest(role=user.primary_role):
                self.client.force_login(user)
                empty=self.client.get("/notifications/")
                self.assertContains(empty,"You're all caught up.")
                self.assertContains(empty,f'class="{workspace}-blueprint-background"')
                self.assertContains(empty,'class="notification-center"')
                if user != customer:
                    self.assertContains(empty,"Back to dashboard")
                for read in (False,True):
                    event=DomainEvent.objects.create(event_type="test.notification",object_type="test")
                    Notification.objects.create(recipient=user,event=event,event_type=event.event_type,related_type="test",title=f"Private {user.primary_role} {read}",body="First line\nSecond line",link="/profile/",read_at=timezone.now() if read else None)
                response=self.client.get("/notifications/")
                self.assertContains(response,'class="notification-entry unread"')
                self.assertContains(response,'class="notification-entry"')
                self.assertContains(response,"First line<br>Second line")
                self.assertContains(response,">Unread</span>")
                for other in (customer,owner,admin):
                    if other != user:
                        self.assertNotContains(response,f"Private {other.primary_role}")

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
