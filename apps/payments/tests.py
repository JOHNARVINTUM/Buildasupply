import hashlib,hmac,json,os,time
from unittest.mock import patch
os.environ.setdefault("BUILTASUPPLY_DEMO_WEBHOOK_SECRET", "test-demo-webhook-secret")
from django.contrib.auth import get_user_model
from django.test import TestCase
from apps.accounts.services import register_customer, register_supplier
from apps.catalog.models import Category
from apps.catalog.services import create_product,moderate_product,submit_for_review,transition_supplier
from apps.carts.services import add_item
from apps.customers.models import CustomerAddress
from apps.inventory.services import record_movement
from apps.orders.services import checkout,transition_supplier_order
from apps.wallets.services import balances
from apps.wallets.models import SettlementRecord
from .models import Payment, PaymentReconciliation, RefundWalletReversal, WebhookEvent
from .services import PaymentFailure, approve_refund, complete_refund, confirm_payment, create_refund, initiate_payment, initiate_refund, process_pesoway_webhook, process_refund_webhook, process_webhook, resolve_payment_reconciliation
User=get_user_model()
class PaymentTests(TestCase):
    def setUp(self):
        admin=User.objects.create_superuser("admin@payment.com","Strongpass123!");self.customer=register_customer(email="buyer@payment.com",password1="Strongpass123!",full_name="Buyer",phone="1");CustomerAddress.objects.create(customer=self.customer.customer_profile,recipient_name="Buyer",phone="1",address_line1="x",city="Manila",province="Metro",is_default=True)
        owner,supplier=register_supplier(email="owner@payment.com",password1="Strongpass123!",full_name="Owner",phone="1",legal_name="Legal",display_name="Supply",business_phone="1");p=create_product(supplier=supplier,actor=owner,name="Bolt",sku="B1",category=Category.objects.create(name="Fasteners",slug="fasteners"),description="",unit_of_measure="box",minimum_order_quantity=1,amount_minor=5000);submit_for_review(product=p,actor=owner);moderate_product(product=p,actor=admin,approve=True);transition_supplier(supplier=supplier,actor=admin,status="APPROVED");record_movement(inventory_id=p.inventory.id,actor=owner,movement_type="RESTOCK",quantity_delta=4,reason="Opening");add_item(customer=self.customer.customer_profile,product=p,quantity=2);self.order_id=checkout(customer=self.customer.customer_profile,idempotency_key="checkout") ["master_order_id"];self.product=p
    def _payment(self):
        from apps.orders.models import MasterOrder
        return initiate_payment(customer=self.customer.customer_profile,order=MasterOrder.objects.get(pk=self.order_id),provider_code="demo",method_category="EWALLET",idempotency_key="pay-1")
    def _webhook(self,payment,event_id):
        body=json.dumps({"event_id":event_id,"provider_reference":payment.provider_reference,"merchant_reference":payment.internal_reference,"amount_minor":payment.amount_minor,"currency":payment.currency,"status":"SUCCESS"}).encode()
        signature=hmac.new(os.environ["BUILTASUPPLY_DEMO_WEBHOOK_SECRET"].encode(),body,hashlib.sha256).hexdigest()
        return body,{"X-Builtasupply-Signature":signature}
    def test_webhook_consumes_reservation_once(self):
        result=self._payment();payment=Payment.objects.get(pk=result["payment_id"]);body,headers=self._webhook(payment,"evt-1")
        self.assertFalse(process_webhook(provider_code="demo",raw_body=body,headers=headers)["duplicate"]);self.assertTrue(process_webhook(provider_code="demo",raw_body=body,headers=headers)["duplicate"])
        payment.refresh_from_db();self.product.inventory.refresh_from_db();self.assertEqual(payment.status,"PAID");self.assertEqual(self.product.inventory.reserved_quantity,0);self.assertEqual(self.product.inventory.sold_quantity,2);self.assertEqual(self.product.inventory.movements.filter(movement_type="SALE").count(),1)
    def test_invalid_signature_and_payment_idempotency(self):
        first=self._payment();second=self._payment();self.assertTrue(second["idempotent"])
        with self.assertRaises(PaymentFailure):process_webhook(provider_code="demo",raw_body=b'{}',headers={"X-Builtasupply-Signature":"bad"})

    def test_different_keys_reuse_the_one_pending_attempt(self):
        first=self._payment();second=initiate_payment(customer=self.customer.customer_profile,order=Payment.objects.get(pk=first["payment_id"]).master_order,provider_code="demo",method_category="EWALLET",idempotency_key="pay-2")
        self.assertTrue(second["pending_attempt_reused"]);self.assertEqual(first["attempt_id"],second["attempt_id"]);self.assertEqual(Payment.objects.get(pk=first["payment_id"]).attempts.count(),1)

    def test_failed_attempt_can_retry_with_a_new_key_without_two_active_attempts(self):
        first=self._payment();payment=Payment.objects.get(pk=first["payment_id"]);payment.attempts.update(status="FAILED")
        retry=initiate_payment(customer=self.customer.customer_profile,order=payment.master_order,provider_code="demo",method_category="EWALLET",idempotency_key="retry-key")
        payment.refresh_from_db();self.assertNotEqual(first["attempt_id"],retry["attempt_id"]);self.assertEqual(payment.attempts.filter(status="PENDING").count(),1)

    def test_paid_webhook_rejects_missing_or_incorrect_verified_values(self):
        payment=Payment.objects.get(pk=self._payment()["payment_id"])
        for event_id,changes in [("missing-amount",{"amount_minor":None}),("wrong-amount",{"amount_minor":1}),("missing-currency",{"currency":None}),("wrong-currency",{"currency":"USD"}),("wrong-reference",{"merchant_reference":"wrong"})]:
            payload={"event_id":event_id,"provider_reference":payment.provider_reference,"merchant_reference":payment.internal_reference,"amount_minor":payment.amount_minor,"currency":"PHP","status":"SUCCESS"};payload.update(changes)
            body=json.dumps({key:value for key,value in payload.items() if value is not None}).encode();signature=hmac.new(os.environ["BUILTASUPPLY_DEMO_WEBHOOK_SECRET"].encode(),body,hashlib.sha256).hexdigest()
            with self.assertRaises(PaymentFailure):process_webhook(provider_code="demo",raw_body=body,headers={"X-Builtasupply-Signature":signature})
        payment.refresh_from_db();self.assertEqual(payment.status,"PENDING")
    def test_refund_allocation_and_over_refund_blocked(self):
        result=self._payment();payment=Payment.objects.get(pk=result["payment_id"]);confirm_payment(payment=payment,provider_event_id="evt-refund",event_type="SUCCESS",normalized_status="PAID");payment.refresh_from_db();so=payment.master_order.supplier_orders.first();item=so.items.first()
        refund=create_refund(payment=payment,actor=User.objects.get(email="admin@payment.com"),allocations=[{"supplier_order":so,"order_item":item,"amount_minor":1000}],idempotency_key="refund-1",reason="Test")
        self.assertEqual(refund.amount_minor,1000)
        with self.assertRaises(PaymentFailure):create_refund(payment=payment,actor=User.objects.get(email="admin@payment.com"),allocations=[{"supplier_order":so,"order_item":item,"amount_minor":10000}],idempotency_key="refund-2",reason="Test")

    def _approved_refund(self, payment, amount, key="refund-lifecycle"):
        admin=User.objects.get(email="admin@payment.com");so=payment.master_order.supplier_orders.first();item=so.items.first()
        refund=create_refund(payment=payment,actor=admin,allocations=[{"supplier_order":so,"order_item":item,"quantity":1,"amount_minor":amount}],idempotency_key=key,reason="Test refund")
        approve_refund(refund=refund,actor=admin,approve=True);return initiate_refund(refund=refund,actor=admin)

    def test_refund_partial_completion_updates_payment_and_wallet_once(self):
        payment=Payment.objects.get(pk=self._payment()["payment_id"]);confirm_payment(payment=payment,provider_event_id="evt-paid-partial",event_type="SUCCESS",normalized_status="PAID")
        refund=self._approved_refund(payment,5000)
        completed=complete_refund(refund=refund,provider_event_id="refund-event-partial",event_type="SUCCESS",normalized_status="COMPLETED",actor=User.objects.get(email="admin@payment.com"))
        complete_refund(refund=completed,provider_event_id="refund-event-partial",event_type="SUCCESS",normalized_status="COMPLETED")
        payment.refresh_from_db();wallet=payment.master_order.supplier_orders.first().supplier.wallets.get();self.assertEqual(completed.status,"COMPLETED");self.assertEqual(payment.refunded_minor,5000);self.assertEqual(payment.status,"PARTIALLY_REFUNDED")
        self.assertEqual(wallet.entries.filter(entry_type="REFUND").count(),1);self.assertEqual(RefundWalletReversal.objects.get().status,"APPLIED")

    def test_full_refund_provider_webhook_and_failure_do_not_fake_completion(self):
        payment=Payment.objects.get(pk=self._payment()["payment_id"]);confirm_payment(payment=payment,provider_event_id="evt-paid-full",event_type="SUCCESS",normalized_status="PAID")
        failed=self._approved_refund(payment,1000,"refund-failed");complete_refund(refund=failed,provider_event_id="refund-event-failed",event_type="FAILED",normalized_status="FAILED")
        failed.refresh_from_db();payment.refresh_from_db();self.assertEqual(failed.status,"FAILED");self.assertEqual(payment.refunded_minor,0)
        refund=self._approved_refund(payment,9000,"refund-full")
        body=json.dumps({"kind":"REFUND","event_id":"refund-event-full","provider_reference":refund.provider_reference,"status":"SUCCESS","amount_minor":9000,"currency":"PHP"}).encode();signature=hmac.new(os.environ["BUILTASUPPLY_DEMO_WEBHOOK_SECRET"].encode(),body,hashlib.sha256).hexdigest()
        process_refund_webhook(provider_code="demo",raw_body=body,headers={"X-Builtasupply-Signature":signature})
        payment.refresh_from_db();refund.refresh_from_db();self.assertEqual(refund.status,"COMPLETED");self.assertEqual(payment.refunded_minor,9000);self.assertEqual(payment.status,"PARTIALLY_REFUNDED")

    def test_full_refund_marks_payment_refunded(self):
        payment=Payment.objects.get(pk=self._payment()["payment_id"]);confirm_payment(payment=payment,provider_event_id="evt-paid-total",event_type="SUCCESS",normalized_status="PAID")
        refund=self._approved_refund(payment,10000,"refund-total")
        complete_refund(refund=refund,provider_event_id="refund-event-total",event_type="SUCCESS",normalized_status="COMPLETED")
        payment.refresh_from_db();refund.refresh_from_db();self.assertEqual(refund.status,"COMPLETED");self.assertEqual(payment.refunded_minor,10000);self.assertEqual(payment.status,"REFUNDED")

    def test_fully_refunded_online_order_never_increases_lifetime_earned(self):
        payment=Payment.objects.get(pk=self._payment()["payment_id"]);confirm_payment(payment=payment,provider_event_id="evt-paid-refunded-before-acceptance",event_type="SUCCESS",normalized_status="PAID")
        refund=self._approved_refund(payment,10000,"refund-before-acceptance");complete_refund(refund=refund,provider_event_id="refund-event-before-acceptance",event_type="SUCCESS",normalized_status="COMPLETED")
        supplier_order=payment.master_order.supplier_orders.get();transition_supplier_order(supplier_order=supplier_order,actor=User.objects.get(email="owner@payment.com"),next_status="CONFIRMED")
        wallet=supplier_order.supplier.wallets.get();self.assertEqual(balances(wallet)["pending"],0);self.assertEqual(balances(wallet)["lifetime_earned"],0)

    def test_refund_rejects_non_admin_and_excessive_item_quantity(self):
        payment=Payment.objects.get(pk=self._payment()["payment_id"]);confirm_payment(payment=payment,provider_event_id="evt-paid-auth",event_type="SUCCESS",normalized_status="PAID")
        so=payment.master_order.supplier_orders.first();item=so.items.first();admin=User.objects.get(email="admin@payment.com")
        with self.assertRaises(Exception):create_refund(payment=payment,actor=self.customer,allocations=[{"supplier_order":so,"order_item":item,"amount_minor":1000}],idempotency_key="refund-no-auth",reason="Test")
        with self.assertRaises(PaymentFailure):create_refund(payment=payment,actor=admin,allocations=[{"supplier_order":so,"order_item":item,"quantity":3,"amount_minor":1000}],idempotency_key="refund-quantity",reason="Test")

    def test_released_wallet_never_becomes_negative_after_refund(self):
        payment=Payment.objects.get(pk=self._payment()["payment_id"]);confirm_payment(payment=payment,provider_event_id="evt-paid-wallet",event_type="SUCCESS",normalized_status="PAID")
        from apps.wallets.services import release_settlement
        settlement=payment.master_order.supplier_orders.first().supplier.wallets.get().settlements.get();settlement.supplier_order.status="COMPLETED";settlement.supplier_order.save();release_settlement(settlement)
        refund=self._approved_refund(payment,10000,"refund-released");complete_refund(refund=refund,provider_event_id="refund-event-released",event_type="SUCCESS",normalized_status="COMPLETED")
        wallet=payment.master_order.supplier_orders.first().supplier.wallets.get();wallet.refresh_from_db();self.assertEqual(wallet.available_cached,0);self.assertEqual(RefundWalletReversal.objects.get().bucket,"AVAILABLE")

    def _expire_order(self):
        from django.core.management import call_command
        from django.utils import timezone
        from apps.inventory.models import InventoryReservation
        InventoryReservation.objects.filter(supplier_order__master_order_id=self.order_id).update(expires_at=timezone.now())
        call_command("expire_reservations")

    def test_late_paid_webhook_is_durable_and_idempotent_without_fulfillment(self):
        result=self._payment();payment=Payment.objects.get(pk=result["payment_id"])
        self._expire_order()
        body,headers=self._webhook(payment,"evt-late")
        first=process_webhook(provider_code="demo",raw_body=body,headers=headers)
        second=process_webhook(provider_code="demo",raw_body=body,headers=headers)
        payment.refresh_from_db();payment.master_order.refresh_from_db();self.product.inventory.refresh_from_db()
        reconciliation=PaymentReconciliation.objects.get(payment=payment)
        self.assertTrue(first["reconciliation_required"]);self.assertTrue(second["duplicate"])
        self.assertEqual(second["reconciliation_id"],str(reconciliation.id))
        self.assertEqual(payment.status,"PENDING");self.assertEqual(payment.master_order.status,"CANCELLED")
        self.assertEqual(self.product.inventory.sold_quantity,0)
        self.assertEqual(SettlementRecord.objects.count(),0)
        self.assertEqual(WebhookEvent.objects.get(provider_event_id="evt-late").processing_status,"LATE_PAYMENT_REQUIRES_RECONCILIATION")
        self.assertEqual(reconciliation.history.count(),1)

    def test_superadmin_can_reallocate_late_payment_once(self):
        result=self._payment();payment=Payment.objects.get(pk=result["payment_id"]);self._expire_order()
        body,headers=self._webhook(payment,"evt-reallocate");process_webhook(provider_code="demo",raw_body=body,headers=headers)
        reconciliation=PaymentReconciliation.objects.get(payment=payment)
        admin=User.objects.get(email="admin@payment.com")
        resolved=resolve_payment_reconciliation(reconciliation=reconciliation,actor=admin,resolution="REALLOCATE",notes="Stock rechecked")
        duplicate=resolve_payment_reconciliation(reconciliation=reconciliation,actor=admin,resolution="REALLOCATE",notes="retry")
        payment.refresh_from_db();payment.master_order.refresh_from_db();self.product.inventory.refresh_from_db()
        self.assertEqual(resolved.status,"REALLOCATED");self.assertEqual(duplicate.id,resolved.id)
        self.assertEqual(payment.status,"PAID");self.assertEqual(payment.master_order.status,"PROCESSING")
        self.assertEqual(self.product.inventory.sold_quantity,2)
        self.assertEqual(self.product.inventory.movements.filter(movement_type="SALE").count(),1)

    def test_reallocation_fails_safely_when_stock_is_not_available(self):
        result=self._payment();payment=Payment.objects.get(pk=result["payment_id"]);self._expire_order()
        body,headers=self._webhook(payment,"evt-no-stock");process_webhook(provider_code="demo",raw_body=body,headers=headers)
        self.product.inventory.available_quantity=0;self.product.inventory.status="OUT_OF_STOCK";self.product.inventory.save()
        reconciliation=PaymentReconciliation.objects.get(payment=payment)
        with self.assertRaises(PaymentFailure):resolve_payment_reconciliation(reconciliation=reconciliation,actor=User.objects.get(email="admin@payment.com"),resolution="REALLOCATE")
        reconciliation.refresh_from_db();payment.refresh_from_db();self.assertEqual(reconciliation.status,"OPEN");self.assertEqual(payment.status,"PENDING")

    def test_refund_required_is_a_record_not_a_fake_refund_and_requires_superadmin(self):
        result=self._payment();payment=Payment.objects.get(pk=result["payment_id"]);self._expire_order()
        body,headers=self._webhook(payment,"evt-refund-required");process_webhook(provider_code="demo",raw_body=body,headers=headers)
        reconciliation=PaymentReconciliation.objects.get(payment=payment)
        with self.assertRaises(Exception):resolve_payment_reconciliation(reconciliation=reconciliation,actor=self.customer,resolution="REFUND_REQUIRED")
        resolved=resolve_payment_reconciliation(reconciliation=reconciliation,actor=User.objects.get(email="admin@payment.com"),resolution="REFUND_REQUIRED",notes="Provider refund needed")
        self.assertEqual(resolved.status,"REFUND_REQUIRED");self.assertEqual(payment.refunds.count(),0)


class PaymentBrowserWorkflowTests(PaymentTests):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.customer)

    def _select_url(self):
        return f"/shop/orders/{self.order_id}/payment/"

    def _payload(self):
        return {
            "method_category": "EWALLET",
            "idempotency_key": self.client.session[f"customer_payment_idempotency:{self.order_id}"],
        }

    def test_customer_can_start_demo_payment_without_marking_order_paid(self):
        response = self.client.get(self._select_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Amount due")
        response = self.client.post(self._select_url(), self._payload(), follow=True)
        self.assertEqual(response.status_code, 200)
        payment = Payment.objects.get(master_order_id=self.order_id)
        self.assertEqual(payment.amount_minor, 10000)
        self.assertEqual(payment.currency, "PHP")
        self.assertEqual(payment.status, "PENDING")
        payment.master_order.refresh_from_db()
        self.assertEqual(payment.master_order.payment_status, "PENDING")
        self.assertContains(response, "Payment is confirmed only after a verified provider webhook")

    def test_repeated_browser_submission_creates_one_attempt(self):
        self.client.get(self._select_url())
        payload = self._payload()
        self.assertEqual(self.client.post(self._select_url(), payload).status_code, 302)
        self.assertEqual(self.client.post(self._select_url(), payload).status_code, 302)
        payment = Payment.objects.get(master_order_id=self.order_id)
        self.assertEqual(payment.attempts.count(), 1)

    def test_payment_pages_are_customer_scoped_and_browser_cannot_confirm(self):
        self.client.get(self._select_url())
        self.client.post(self._select_url(), self._payload())
        payment = Payment.objects.get(master_order_id=self.order_id)
        self.assertEqual(self.client.get(f"/shop/payments/{payment.pk}/").status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, "PENDING")
        other = register_customer(email="other-payment-browser@example.com", password1="Strongpass123!", full_name="Other", phone="7")
        self.client.force_login(other)
        self.assertEqual(self.client.get(self._select_url()).status_code, 404)
        self.assertEqual(self.client.get(f"/shop/payments/{payment.pk}/").status_code, 404)


class PesoWayIntegrationTests(PaymentTests):
    def setUp(self):
        super().setUp()
        self.environment = {
            "PESOWAY_BASE_URL": "http://pesoway.test",
            "PESOWAY_API_KEY": "pw_test_scoped_key",
            "PESOWAY_WEBHOOK_SECRET": "whsec_test_secret",
        }
        self.environment_patch = patch.dict(os.environ, self.environment)
        self.environment_patch.start()
        self.addCleanup(self.environment_patch.stop)

    def _create_response(self, payment):
        return {"data": {"id": "2c1fcdee-3f58-4ed8-9a7d-458b4cf90511", "amount_centavos": payment.amount_minor, "currency": "PHP", "merchant_reference": payment.provider_merchant_reference, "status": "requires_payment_method", "checkout_url": "/checkout/2c1fcdee-3f58-4ed8-9a7d-458b4cf90511/"}}

    def _start(self):
        from apps.orders.models import MasterOrder
        order = MasterOrder.objects.get(pk=self.order_id)
        with patch("apps.payments.adapters.PesoWayAdapter._request_json") as request_json:
            request_json.return_value = {"data": {"id": "2c1fcdee-3f58-4ed8-9a7d-458b4cf90511", "amount_centavos": order.total_minor, "currency": "PHP", "merchant_reference": f"buildasupply-order-{order.id}", "status": "requires_payment_method", "checkout_url": "/checkout/2c1fcdee-3f58-4ed8-9a7d-458b4cf90511/"}}
            result = initiate_payment(customer=self.customer.customer_profile, order=order, provider_code="pesoway", method_category="HOSTED_CHECKOUT", idempotency_key="pesoway-start", return_url="http://buildasupply.test/payments/pesoway/complete/")
        return result, Payment.objects.get(pk=result["payment_id"])

    def _webhook(self, payment, event_id, event_type="payment_intent.succeeded", status="succeeded"):
        body = json.dumps({"id": event_id, "type": event_type, "data": {"payment_intent": payment.provider_reference, "status": status}}, separators=(",", ":")).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(os.environ["PESOWAY_WEBHOOK_SECRET"].encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
        return body, {"X-PesoWay-Event": event_id, "X-PesoWay-Timestamp": timestamp, "X-PesoWay-Signature": f"v1={signature}"}

    def _status_response(self, payment, status="succeeded", merchant_reference=None):
        return {"data": {"id": payment.provider_reference, "status": status, "merchant_reference": merchant_reference or payment.provider_merchant_reference, "amount_centavos": payment.amount_minor, "currency": payment.currency}}

    def test_intent_creation_maps_centavos_and_is_idempotent(self):
        result, payment = self._start()
        self.assertEqual(payment.amount_minor, 10000)
        self.assertEqual(payment.provider_reference, "2c1fcdee-3f58-4ed8-9a7d-458b4cf90511")
        self.assertEqual(payment.provider_merchant_reference, f"buildasupply-order-{self.order_id}")
        self.assertEqual(result["instruction_url"], "http://pesoway.test/checkout/2c1fcdee-3f58-4ed8-9a7d-458b4cf90511/")
        again = initiate_payment(customer=self.customer.customer_profile, order=payment.master_order, provider_code="pesoway", method_category="HOSTED_CHECKOUT", idempotency_key="pesoway-start", return_url="http://buildasupply.test/payments/pesoway/complete/")
        self.assertTrue(again["idempotent"])
        self.assertEqual(Payment.objects.get(pk=payment.pk).attempts.count(), 1)

    def test_return_page_never_marks_a_payment_paid(self):
        _, payment = self._start()
        self.client.force_login(self.customer)
        response = self.client.get(f"/payments/pesoway/complete/?payment_intent={payment.provider_reference}&status=succeeded")
        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, "PENDING")
        self.assertContains(response, "Returning here never marks an order as paid")

    def test_valid_signed_webhook_confirms_once(self):
        _, payment = self._start()
        body, headers = self._webhook(payment, "event-pesoway-success")
        with patch("apps.payments.adapters.PesoWayAdapter._request_json", return_value=self._status_response(payment)):
            self.assertFalse(process_pesoway_webhook(raw_body=body, headers=headers)["duplicate"])
            self.assertTrue(process_pesoway_webhook(raw_body=body, headers=headers)["duplicate"])
        payment.refresh_from_db()
        payment.master_order.refresh_from_db()
        self.assertEqual(payment.status, "PAID")
        self.assertEqual(payment.master_order.status, "PROCESSING")
        self.assertEqual(payment.master_order.supplier_orders.first().inventory_reservations.filter(status="CONSUMED").count(), 1)

    def test_invalid_signature_and_cross_order_reference_are_rejected(self):
        _, payment = self._start()
        body, headers = self._webhook(payment, "event-invalid")
        headers["X-PesoWay-Signature"] = "v1=invalid"
        with self.assertRaises(PaymentFailure):
            process_pesoway_webhook(raw_body=body, headers=headers)
        body, headers = self._webhook(payment, "event-wrong-order")
        with patch("apps.payments.adapters.PesoWayAdapter._request_json", return_value=self._status_response(payment, merchant_reference="buildasupply-order-other")):
            with self.assertRaises(PaymentFailure):
                process_pesoway_webhook(raw_body=body, headers=headers)
        payment.refresh_from_db()
        self.assertEqual(payment.status, "PENDING")
        self.assertFalse(WebhookEvent.objects.filter(provider_event_id="event-wrong-order").exists())

    def test_canceled_intent_does_not_mark_order_paid(self):
        _, payment = self._start()
        body, headers = self._webhook(payment, "event-pesoway-canceled", "payment_intent.canceled", "canceled")
        with patch("apps.payments.adapters.PesoWayAdapter._request_json", return_value=self._status_response(payment, status="canceled")):
            process_pesoway_webhook(raw_body=body, headers=headers)
        payment.refresh_from_db()
        payment.master_order.refresh_from_db()
        self.assertEqual(payment.status, "CANCELLED")
        self.assertNotEqual(payment.master_order.payment_status, "PAID")

    def test_webhook_rollback_does_not_leave_a_paid_payment(self):
        _, payment = self._start()
        body, headers = self._webhook(payment, "event-pesoway-rollback")
        with patch("apps.payments.adapters.PesoWayAdapter._request_json", return_value=self._status_response(payment)), patch("apps.wallets.services.post_payment_earnings", side_effect=RuntimeError("ledger unavailable")):
            with self.assertRaises(RuntimeError):
                process_pesoway_webhook(raw_body=body, headers=headers)
        payment.refresh_from_db()
        self.assertEqual(payment.status, "PENDING")
        self.assertFalse(WebhookEvent.objects.filter(provider_event_id="event-pesoway-rollback").exists())
