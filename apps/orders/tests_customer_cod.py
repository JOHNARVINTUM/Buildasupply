from django.test import TestCase

from apps.accounts.services import register_customer
from apps.orders.models import MasterOrder
from apps.payments.models import CODCollection, CODReceiptConfirmation
from apps.payments.services import PaymentFailure, initiate_payment, select_cod
from apps.payments.tests_cod import CODBackendTests, MultiSupplierCODTests


class CustomerCODBrowserTests(CODBackendTests):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.customer)

    def test_customer_selects_cod_from_confirmation_and_selection_is_idempotent(self):
        page = self.client.get(f"/shop/orders/{self.order.pk}/confirmation/")
        self.assertContains(page, "Choose cash on delivery")
        response = self.client.post(f"/shop/orders/{self.order.pk}/cash-on-delivery/")
        self.assertRedirects(response, f"/shop/orders/{self.order.pk}/confirmation/", fetch_redirect_response=False)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "COD_COMMITTED")
        self.assertEqual(self.order.payment_status, "COD_PENDING")
        again = self.client.post(f"/shop/orders/{self.order.pk}/cash-on-delivery/")
        self.assertRedirects(again, f"/shop/orders/{self.order.pk}/confirmation/", fetch_redirect_response=False)
        self.assertEqual(self.order.cod_commitment.status, "ACTIVE")
        confirmed = self.client.get(f"/shop/orders/{self.order.pk}/confirmation/")
        self.assertContains(confirmed, "Cash on Delivery")
        self.assertContains(confirmed, "has not been collected yet")

    def test_other_customer_cannot_select_or_view_order(self):
        other = register_customer(email="other-customer-ui@cod.com", password1="Strongpass123!", full_name="Other", phone="4")
        self.client.force_login(other)
        self.assertEqual(self.client.get(f"/shop/orders/{self.order.pk}/").status_code, 404)
        self.assertEqual(self.client.post(f"/shop/orders/{self.order.pk}/cash-on-delivery/").status_code, 404)

    def test_cod_rejects_expired_or_online_payment_orders_and_online_payment_remains_available(self):
        self.so.inventory_reservations.update(status="RELEASED")
        response = self.client.post(f"/shop/orders/{self.order.pk}/cash-on-delivery/")
        self.assertRedirects(response, f"/shop/orders/{self.order.pk}/confirmation/", fetch_redirect_response=False)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "PENDING")

        # A fresh order with an initiated online payment keeps the online path exclusive.
        from apps.carts.services import add_item
        from apps.orders.services import checkout
        add_item(customer=self.customer.customer_profile, product=self.product, quantity=1)
        fresh = MasterOrder.objects.get(pk=checkout(customer=self.customer.customer_profile, idempotency_key="customer-ui-online")["master_order_id"])
        initiate_payment(customer=self.customer.customer_profile, order=fresh, provider_code="demo", method_category="EWALLET", idempotency_key="customer-ui-online-payment")
        response = self.client.post(f"/shop/orders/{fresh.pk}/cash-on-delivery/")
        self.assertRedirects(response, f"/shop/orders/{fresh.pk}/confirmation/", fetch_redirect_response=False)
        self.assertEqual(self.client.get(f"/shop/orders/{fresh.pk}/payment/").status_code, 302)

    def test_customer_cannot_confirm_before_delivery_or_modify_collection(self):
        select_cod(customer=self.customer.customer_profile, order=self.order)
        early = self.client.post(f"/shop/orders/{self.order.pk}/supplier-orders/{self.so.pk}/confirm-receipt/")
        self.assertRedirects(early, f"/shop/orders/{self.order.pk}/", fetch_redirect_response=False)
        self.assertEqual(CODReceiptConfirmation.objects.count(), 0)
        self.assertEqual(self.client.post(f"/supplier/orders/{self.so.pk}/collect/", {"amount_minor": 1, "currency": "USD", "collection_reference": "bad"}).status_code, 404)

    def test_customer_can_cancel_only_before_supplier_acceptance(self):
        select_cod(customer=self.customer.customer_profile, order=self.order)
        response = self.client.post(f"/shop/orders/{self.order.pk}/cancel-cod/", {"reason": "No longer needed"})
        self.assertRedirects(response, f"/shop/orders/{self.order.pk}/", fetch_redirect_response=False)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "CANCELLED")
        self.assertEqual(self.so.inventory_reservations.get().status, "RELEASED")

    def test_customer_sees_collection_status_but_not_collection_evidence(self):
        select_cod(customer=self.customer.customer_profile, order=self.order)
        self.so.status = "DELIVERED"
        self.so.save(update_fields=["status"])
        from apps.payments.services import record_cod_collection
        record_cod_collection(supplier_order=self.so, actor=self.owner, amount_minor=self.so.total_minor, currency="PHP", collection_reference="private-reference", evidence_metadata={"secret": "not-for-customer"})
        page = self.client.get(f"/shop/orders/{self.order.pk}/")
        self.assertContains(page, "Collection recorded")
        self.assertNotContains(page, "private-reference")
        self.assertNotContains(page, "not-for-customer")


class CustomerCODMultiSupplierTests(MultiSupplierCODTests):
    def setUp(self):
        super().setUp()
        select_cod(customer=self.customer_multi.customer_profile, order=self.order_multi)
        self.client.force_login(self.customer_multi)

    def test_supplier_order_statuses_and_receipt_confirmations_are_independent(self):
        self.a.status = "DELIVERED"
        self.a.save(update_fields=["status"])
        self.b.status = "PREPARING"
        self.b.save(update_fields=["status"])
        page = self.client.get(f"/shop/orders/{self.order_multi.pk}/")
        self.assertContains(page, "Delivered")
        self.assertContains(page, "Preparing")
        response = self.client.post(f"/shop/orders/{self.order_multi.pk}/supplier-orders/{self.a.pk}/confirm-receipt/")
        self.assertRedirects(response, f"/shop/orders/{self.order_multi.pk}/", fetch_redirect_response=False)
        self.assertTrue(CODReceiptConfirmation.objects.filter(supplier_order=self.a).exists())
        self.assertFalse(CODReceiptConfirmation.objects.filter(supplier_order=self.b).exists())
        self.assertContains(self.client.get(f"/shop/orders/{self.order_multi.pk}/"), "Confirmed")
