from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from apps.accounts.services import register_customer, register_staff_buyer
from apps.orders.models import MasterOrder
User=get_user_model()
class AdminOperationsTests(TestCase):
    def setUp(self):self.admin=User.objects.create_superuser("admin@ops.com","Strongpass123!");self.customer=User.objects.create_user("customer@ops.com","Strongpass123!")
    def test_non_admin_cannot_access_control_center(self):
        c=APIClient();c.force_authenticate(self.customer);self.assertEqual(c.get("/api/v1/admin/dashboard/").status_code,403)
    def test_admin_dashboard_and_configuration_are_service_backed(self):
        c=APIClient();c.force_authenticate(self.admin);self.assertEqual(c.get("/api/v1/admin/dashboard/").status_code,200)
        response=c.post("/api/v1/admin/configuration/",{"key":"SETTLEMENT_POLICY","version":"v1","value":{"rule":"completion"},"effective_from":"2026-10-02T00:00:00+08:00","activate":True},format="json");self.assertEqual(response.status_code,201)
    def test_superadmin_can_manage_another_user_status_but_not_self(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/operations/users/").status_code,200)
        response=self.client.post(f"/operations/users/{self.customer.id}/status/", {"status":"SUSPENDED"})
        self.assertRedirects(response, "/operations/users/")
        self.customer.refresh_from_db();self.assertEqual(self.customer.account_status,"SUSPENDED")
        self.client.post(f"/operations/users/{self.admin.id}/status/", {"status":"SUSPENDED"})
        self.admin.refresh_from_db();self.assertEqual(self.admin.account_status,"ACTIVE")
    def test_superadmin_can_approve_pending_supplier(self):
        from apps.accounts.services import register_supplier
        _, supplier=register_supplier(email="supplier@ops.com",password1="Strongpass123!",full_name="Owner",phone="1",legal_name="Ops Legal",display_name="Ops Supply",business_phone="1")
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/operations/suppliers/").status_code,200)
        response=self.client.post(f"/operations/suppliers/{supplier.id}/status/", {"status":"APPROVED"})
        self.assertRedirects(response, "/operations/suppliers/")
        supplier.refresh_from_db();self.assertEqual(supplier.approval_status,"APPROVED")
    def test_superadmin_can_open_supplier_item_management(self):
        from apps.accounts.services import register_supplier
        _, supplier=register_supplier(email="items@ops.com",password1="Strongpass123!",full_name="Owner",phone="1",legal_name="Items Legal",display_name="Items Supply",business_phone="1")
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(f"/operations/suppliers/{supplier.id}/products/").status_code,200)

    def test_superadmin_can_create_staff_buyer_with_individual_customer_profile(self):
        self.client.force_login(self.admin)

        response = self.client.post("/operations/staff-buyers/", {
            "full_name": "Assigned Purchaser",
            "email": "staff-buyer@ops.com",
            "phone": "09170000000",
            "password1": "Strongpass123!",
            "password2": "Strongpass123!",
        })

        self.assertRedirects(response, "/operations/staff-buyers/")
        buyer = User.objects.get(email="staff-buyer@ops.com")
        self.assertEqual(buyer.primary_role, User.GlobalRole.STAFF_BUYER)
        self.assertTrue(hasattr(buyer, "customer_profile"))
        self.client.force_login(buyer)
        self.assertEqual(self.client.get("/shop/cart/").status_code, 200)
        self.assertEqual(self.client.get("/account/addresses/").status_code, 200)

    def test_staff_purchase_monitoring_shows_only_staff_buyer_orders(self):
        staff_buyer = register_staff_buyer(
            email="buyer-staff@ops.com",
            password1="Strongpass123!",
            full_name="Staff Buyer",
            phone="09170000001",
            actor=self.admin,
        )
        regular_customer = register_customer(
            email="regular@ops.com",
            password1="Strongpass123!",
            full_name="Regular Customer",
            phone="09170000002",
        )
        staff_order = MasterOrder.objects.create(
            order_number="STAFF-ORDER-1", customer=staff_buyer.customer_profile,
            subtotal_minor=12500, total_minor=12500,
        )
        MasterOrder.objects.create(
            order_number="CUSTOMER-ORDER-1", customer=regular_customer.customer_profile,
            subtotal_minor=25000, total_minor=25000,
        )

        self.client.force_login(self.admin)
        response = self.client.get("/operations/staff-purchases/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, staff_order.order_number)
        self.assertNotContains(response, "CUSTOMER-ORDER-1")
        self.client.force_login(staff_buyer)
        self.assertEqual(self.client.get("/operations/staff-purchases/").status_code, 302)
