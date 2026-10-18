from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
User=get_user_model()
class AdminOperationsTests(TestCase):
    def setUp(self):self.admin=User.objects.create_superuser("admin@ops.com","Strongpass123!");self.customer=User.objects.create_user("customer@ops.com","Strongpass123!")
    def test_non_admin_cannot_access_control_center(self):
        c=APIClient();c.force_authenticate(self.customer);self.assertEqual(c.get("/api/v1/admin/dashboard/").status_code,403)
    def test_admin_dashboard_and_configuration_are_service_backed(self):
        c=APIClient();c.force_authenticate(self.admin);self.assertEqual(c.get("/api/v1/admin/dashboard/").status_code,200)
        response=c.post("/api/v1/admin/configuration/",{"key":"SETTLEMENT_POLICY","version":"v1","value":{"rule":"completion"},"effective_from":"2026-10-02T00:00:00+08:00","activate":True},format="json");self.assertEqual(response.status_code,201)
