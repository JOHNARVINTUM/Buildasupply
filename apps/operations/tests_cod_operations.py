from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.payments.models import CODException, PaymentReconciliation, WebhookEvent
from apps.payments.services import (
    accept_cod_supplier_order,
    confirm_cod_receipt,
    record_cod_collection,
    report_cod_delivery_exception,
    select_cod,
)
from apps.payments.tests_cod import CODBackendTests, MultiSupplierCODTests
from apps.wallets.models import SettlementRecord, WalletLedgerEntry


User = get_user_model()


class CODOperationsTests(CODBackendTests):
    def setUp(self):
        super().setUp()
        select_cod(customer=self.customer.customer_profile, order=self.order)
        self.client.force_login(self.admin)

    def test_only_superadmin_can_access_cod_management_and_dashboard_lists_supplier_order(self):
        response = self.client.get("/operations/cod/orders/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.order_number)
        self.assertEqual(self.client.get(f"/operations/cod/orders/{self.so.pk}/").status_code, 200)
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get("/operations/cod/orders/").status_code, 302)

    def test_failed_delivery_does_not_restore_stock_and_verified_return_releases_once(self):
        exception = report_cod_delivery_exception(supplier_order=self.so, actor=self.owner, status="FAILED_DELIVERY", reason="Customer unavailable")
        self.product.inventory.refresh_from_db()
        before_available = self.product.inventory.available_quantity
        self.client.post(f"/operations/cod/returns/{exception.pk}/verify/", {"reason": "Return received at supplier warehouse"})
        self.product.inventory.refresh_from_db()
        self.assertEqual(self.product.inventory.available_quantity, before_available + 2)
        exception.refresh_from_db()
        self.assertEqual(exception.status, "RETURN_VERIFIED")
        movements = self.product.inventory.movements.filter(movement_type="RESERVATION_RELEASE").count()
        self.client.post(f"/operations/cod/returns/{exception.pk}/verify/", {"reason": "repeat"})
        self.assertEqual(self.product.inventory.movements.filter(movement_type="RESERVATION_RELEASE").count(), movements)

    def test_settlement_release_uses_existing_eligibility_checks_and_is_idempotent(self):
        accept_cod_supplier_order(supplier_order=self.so, actor=self.owner)
        self.so.status = "DELIVERED"
        self.so.save(update_fields=["status"])
        record_cod_collection(supplier_order=self.so, actor=self.owner, amount_minor=self.so.total_minor, currency="PHP", collection_reference="ops-cash")
        confirm_cod_receipt(supplier_order=self.so, customer=self.customer.customer_profile)
        settlement = SettlementRecord.objects.get(supplier_order=self.so)
        response = self.client.post(f"/operations/cod/settlements/{settlement.pk}/release/")
        self.assertRedirects(response, "/operations/cod/settlements/")
        settlement.refresh_from_db()
        self.assertEqual(settlement.status, "RELEASED")
        entries = WalletLedgerEntry.objects.filter(source_id=settlement.pk, entry_type="SETTLEMENT").count()
        self.client.post(f"/operations/cod/settlements/{settlement.pk}/release/")
        self.assertEqual(WalletLedgerEntry.objects.filter(source_id=settlement.pk, entry_type="SETTLEMENT").count(), entries)

    def test_disputes_and_reconciliations_are_visible_without_unsafe_resolution(self):
        report_cod_delivery_exception(supplier_order=self.so, actor=self.owner, status="DISPUTED", reason="Collection challenged")
        self.assertContains(self.client.get("/operations/cod/disputes/"), "Collection challenged")
        webhook = WebhookEvent.objects.create(provider_code="demo", provider_event_id="ops-recon-event", verified=True, raw_body="{}")
        payment = self.order.payments.create(internal_reference="ops-recon-payment", provider_code="demo", method_category="EWALLET", amount_minor=self.order.total_minor, currency="PHP")
        reconciliation = PaymentReconciliation.objects.create(payment=payment, master_order=self.order, webhook_event=webhook, provider_code="demo", provider_event_id="ops-recon-event", amount_minor=self.order.total_minor, currency="PHP")
        page = self.client.get("/operations/cod/reconciliations/")
        self.assertContains(page, "ops-recon-payment")
        response = self.client.post(f"/operations/cod/reconciliations/{reconciliation.pk}/resolve/", {"resolution": "INVESTIGATING", "notes": "Reviewing provider event."})
        self.assertRedirects(response, "/operations/cod/reconciliations/")
        reconciliation.refresh_from_db()
        self.assertEqual(reconciliation.status, "INVESTIGATING")


class CODOperationsMultiSupplierTests(MultiSupplierCODTests):
    def setUp(self):
        super().setUp()
        select_cod(customer=self.customer_multi.customer_profile, order=self.order_multi)
        self.client.force_login(self.admin)

    def test_multi_supplier_order_rows_remain_independent(self):
        page = self.client.get("/operations/cod/orders/")
        self.assertContains(page, self.a.pk)
        self.assertContains(page, self.b.pk)
        self.assertContains(page, self.supplier.display_name)
        self.assertContains(page, self.supplier_b.display_name)
