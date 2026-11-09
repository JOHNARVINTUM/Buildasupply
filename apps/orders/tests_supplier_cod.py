from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.services import register_supplier
from apps.payments.models import CODCollection
from apps.payments.services import confirm_cod_receipt, select_cod
from apps.payments.tests_cod import CODBackendTests
from apps.suppliers.models import SupplierStaffMembership
from apps.orders.models import Delivery, MasterOrder, SupplierOrder
from apps.payments.models import CODCommitment


User = get_user_model()


class SupplierCODBrowserTests(CODBackendTests):
    def setUp(self):
        super().setUp()
        select_cod(customer=self.customer.customer_profile, order=self.order)
        self.client.force_login(self.owner)

    def test_dashboard_is_scoped_and_order_detail_isolated(self):
        owner_b, supplier_b = register_supplier(email="interface-b@cod.com", password1="Strongpass123!", full_name="B", phone="3", legal_name="Interface Legal B", display_name="Interface B", business_phone="3")
        response = self.client.get("/supplier/orders/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.order_number)
        self.assertNotContains(response, "Interface B")
        self.client.force_login(owner_b)
        self.assertEqual(self.client.get(f"/supplier/orders/{self.so.pk}/").status_code, 404)

    def test_dashboard_filter_and_pagination_remain_supplier_scoped(self):
        for index in range(21):
            order = MasterOrder.objects.create(order_number=f"BS-PAGE-{index:03d}", customer=self.customer.customer_profile, currency="PHP", subtotal_minor=100, total_minor=100, status="COD_COMMITTED", payment_status="COD_PENDING")
            CODCommitment.objects.create(master_order=order, selected_by=self.customer)
            supplier_order = SupplierOrder.objects.create(master_order=order, supplier=self.supplier, supplier_name_snapshot=self.supplier.display_name, status="PENDING_SUPPLIER", subtotal_minor=100, total_minor=100, currency="PHP")
            Delivery.objects.create(supplier_order=supplier_order, address_snapshot={})
        response = self.client.get("/supplier/orders/?status=incoming&page=2")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Page 2 of 2")
        self.assertContains(response, "BS-PAGE-000")

    def test_fulfillment_role_is_required_for_actions(self):
        staff = User.objects.create_user("catalog-staff@cod.com", "Strongpass123!", primary_role="SUPPLIER")
        SupplierStaffMembership.objects.create(supplier=self.supplier, user=staff, role="CATALOG_MANAGER")
        self.client.force_login(staff)
        response = self.client.post(f"/supplier/orders/{self.so.pk}/accept/")
        self.assertEqual(response.status_code, 403)
        self.so.refresh_from_db()
        self.assertEqual(self.so.status, "PENDING_SUPPLIER")

    def test_accept_prepare_dispatch_deliver_records_actor_and_delivery(self):
        self.assertRedirects(self.client.post(f"/supplier/orders/{self.so.pk}/accept/"), f"/supplier/orders/{self.so.pk}/", fetch_redirect_response=False)
        self.assertRedirects(self.client.post(f"/supplier/orders/{self.so.pk}/prepare/"), f"/supplier/orders/{self.so.pk}/", fetch_redirect_response=False)
        self.assertRedirects(self.client.post(f"/supplier/orders/{self.so.pk}/ready/"), f"/supplier/orders/{self.so.pk}/", fetch_redirect_response=False)
        bad = self.client.post(f"/supplier/orders/{self.so.pk}/dispatch/", {"carrier_name": "", "tracking_reference": ""})
        self.assertRedirects(bad, f"/supplier/orders/{self.so.pk}/", fetch_redirect_response=False)
        self.assertRedirects(self.client.post(f"/supplier/orders/{self.so.pk}/dispatch/", {"carrier_name": "Supplier delivery", "tracking_reference": "COD-DEL-1", "notes": "Gate 2"}), f"/supplier/orders/{self.so.pk}/", fetch_redirect_response=False)
        self.assertRedirects(self.client.post(f"/supplier/orders/{self.so.pk}/deliver/"), f"/supplier/orders/{self.so.pk}/", fetch_redirect_response=False)
        self.so.refresh_from_db()
        self.assertEqual(self.so.status, "DELIVERED")
        self.assertEqual(self.so.delivery.tracking_reference, "COD-DEL-1")
        self.assertIsNotNone(self.so.delivery.shipped_at)
        self.assertIsNotNone(self.so.delivery.delivered_at)

    def test_dispatch_invalid_state_and_duplicate_acceptance_are_safe(self):
        self.client.post(f"/supplier/orders/{self.so.pk}/accept/")
        duplicate = self.client.post(f"/supplier/orders/{self.so.pk}/accept/")
        self.assertRedirects(duplicate, f"/supplier/orders/{self.so.pk}/", fetch_redirect_response=False)
        invalid = self.client.post(f"/supplier/orders/{self.so.pk}/dispatch/", {"carrier_name": "Delivery", "tracking_reference": "R-1"})
        self.assertRedirects(invalid, f"/supplier/orders/{self.so.pk}/", fetch_redirect_response=False)
        self.so.refresh_from_db()
        self.assertEqual(self.so.status, "CONFIRMED")

    def test_collection_requires_exact_hidden_server_validated_values_and_receipt_is_visible(self):
        self.so.status = "DELIVERED"
        self.so.save(update_fields=["status"])
        wrong_amount = self.client.post(f"/supplier/orders/{self.so.pk}/collect/", {"amount_minor": self.so.total_minor - 1, "currency": "PHP", "collection_reference": "cash-1"})
        self.assertRedirects(wrong_amount, f"/supplier/orders/{self.so.pk}/", fetch_redirect_response=False)
        self.assertEqual(CODCollection.objects.count(), 0)
        wrong_currency = self.client.post(f"/supplier/orders/{self.so.pk}/collect/", {"amount_minor": self.so.total_minor, "currency": "USD", "collection_reference": "cash-1"})
        self.assertRedirects(wrong_currency, f"/supplier/orders/{self.so.pk}/", fetch_redirect_response=False)
        missing_reference = self.client.post(f"/supplier/orders/{self.so.pk}/collect/", {"amount_minor": self.so.total_minor, "currency": "PHP", "collection_reference": ""})
        self.assertRedirects(missing_reference, f"/supplier/orders/{self.so.pk}/", fetch_redirect_response=False)
        response = self.client.post(f"/supplier/orders/{self.so.pk}/collect/", {"amount_minor": self.so.total_minor, "currency": "PHP", "collection_reference": "cash-1", "evidence_notes": "received"})
        self.assertRedirects(response, f"/supplier/orders/{self.so.pk}/", fetch_redirect_response=False)
        self.assertEqual(CODCollection.objects.count(), 1)
        duplicate = self.client.post(f"/supplier/orders/{self.so.pk}/collect/", {"amount_minor": self.so.total_minor, "currency": "PHP", "collection_reference": "cash-1"})
        self.assertRedirects(duplicate, f"/supplier/orders/{self.so.pk}/", fetch_redirect_response=False)
        detail = self.client.get(f"/supplier/orders/{self.so.pk}/")
        self.assertContains(detail, "Awaiting customer receipt confirmation")
        self.assertNotContains(detail, "Confirm receipt")
        confirm_cod_receipt(supplier_order=self.so, customer=self.customer.customer_profile)
        detail = self.client.get(f"/supplier/orders/{self.so.pk}/")
        self.assertContains(detail, "Customer receipt confirmed")

    def test_post_only_and_exception_reporting(self):
        self.assertEqual(self.client.get(f"/supplier/orders/{self.so.pk}/accept/").status_code, 405)
        response = self.client.post(f"/supplier/orders/{self.so.pk}/exception/", {"status": "FAILED_DELIVERY", "reason": "Customer unavailable"})
        self.assertRedirects(response, f"/supplier/orders/{self.so.pk}/", fetch_redirect_response=False)
        detail = self.client.get(f"/supplier/orders/{self.so.pk}/")
        self.assertContains(detail, "Customer unavailable")
