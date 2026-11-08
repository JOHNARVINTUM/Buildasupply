from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from apps.accounts.services import register_customer, register_supplier
from apps.catalog.models import Category, ProductPrice
from apps.catalog.services import create_product, moderate_product, submit_for_review, transition_supplier
from apps.carts.services import add_item, get_active_cart
from apps.customers.models import CustomerAddress
from apps.inventory.services import record_movement
from .models import MasterOrder
from .services import CheckoutFailure, checkout
User=get_user_model()
class CheckoutTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_superuser("admin@order.com","Strongpass123!")
        self.customer=register_customer(email="buyer@order.com",password1="Strongpass123!",full_name="Buyer",phone="1")
        CustomerAddress.objects.create(customer=self.customer.customer_profile,recipient_name="Buyer",phone="1",address_line1="1 Build St",city="Manila",province="Metro Manila",is_default=True)
        self.owner,self.supplier=register_supplier(email="owner@order.com",password1="Strongpass123!",full_name="Owner",phone="1",legal_name="Legal",display_name="Supply",business_phone="1")
        category=Category.objects.create(name="Hardware",slug="hardware")
        self.product=create_product(supplier=self.supplier,actor=self.owner,name="Nails",sku="N1",category=category,description="",unit_of_measure="box",minimum_order_quantity=2,amount_minor=10000)
        submit_for_review(product=self.product,actor=self.owner);moderate_product(product=self.product,actor=self.admin,approve=True);transition_supplier(supplier=self.supplier,actor=self.admin,status="APPROVED")
        record_movement(inventory_id=self.product.inventory.id,actor=self.owner,movement_type="RESTOCK",quantity_delta=10,reason="Opening")
    def test_checkout_creates_snapshots_and_reserves_not_sells(self):
        add_item(customer=self.customer.customer_profile,product=self.product,quantity=5)
        result=checkout(customer=self.customer.customer_profile,idempotency_key="request-1")
        order=MasterOrder.objects.get(pk=result["master_order_id"]);self.assertEqual(order.total_minor,50000);self.assertEqual(order.supplier_orders.count(),1);self.assertEqual(order.supplier_orders.first().items.first().product_name,"Nails")
        self.product.inventory.refresh_from_db();self.assertEqual(self.product.inventory.available_quantity,5);self.assertEqual(self.product.inventory.reserved_quantity,5);self.assertEqual(self.product.inventory.sold_quantity,0)
        self.assertEqual(get_active_cart(self.customer.customer_profile).status,"ACTIVE") if False else self.assertEqual(order.supplier_orders.first().inventory_reservations.count(),1)
    def test_price_change_rolls_back_without_reservation(self):
        add_item(customer=self.customer.customer_profile,product=self.product,quantity=2)
        old=self.product.prices.get();old.is_active=False;old.save()
        from django.utils import timezone
        ProductPrice.objects.create(product=self.product,amount_minor=11000,currency="PHP",starts_at=timezone.now())
        with self.assertRaises(CheckoutFailure):checkout(customer=self.customer.customer_profile,idempotency_key="request-2")
        self.assertEqual(MasterOrder.objects.count(),0);self.product.inventory.refresh_from_db();self.assertEqual(self.product.inventory.available_quantity,10)
    def test_idempotency_returns_same_order_and_no_duplicate_reservation(self):
        add_item(customer=self.customer.customer_profile,product=self.product,quantity=2)
        first=checkout(customer=self.customer.customer_profile,idempotency_key="same")
        second=checkout(customer=self.customer.customer_profile,idempotency_key="same")
        self.assertEqual(first["master_order_id"],second["master_order_id"]);self.assertEqual(MasterOrder.objects.count(),1)


class CheckoutBrowserWorkflowTests(CheckoutTests):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.customer)

    def _checkout_page(self):
        return self.client.get("/shop/checkout/")

    def _submit_data(self, address=None):
        session = self.client.session
        return {
            "delivery_address": (address or self.customer.customer_profile.addresses.get(is_default=True)).pk,
            "idempotency_key": session["customer_checkout_idempotency"],
        }

    def test_checkout_page_lists_owned_addresses_and_selected_default(self):
        second = CustomerAddress.objects.create(customer=self.customer.customer_profile, recipient_name="Buyer Two", phone="2", address_line1="2 Build St", city="Quezon City", province="Metro Manila", is_default=False)
        add_item(customer=self.customer.customer_profile, product=self.product, quantity=2)
        response = self._checkout_page()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1 Build St")
        self.assertContains(response, second.address_line1)
        self.assertContains(response, "Place order")

    def test_checkout_creates_order_with_selected_address_reservation_and_confirmation(self):
        selected = CustomerAddress.objects.create(customer=self.customer.customer_profile, recipient_name="Project Site", phone="3", address_line1="99 Project Road", city="Pasig", province="Metro Manila", is_default=False)
        add_item(customer=self.customer.customer_profile, product=self.product, quantity=3)
        self._checkout_page()
        response = self.client.post("/shop/checkout/submit/", self._submit_data(selected), follow=True)
        self.assertEqual(response.status_code, 200)
        order = MasterOrder.objects.get(customer=self.customer.customer_profile)
        self.assertEqual(order.status, "PENDING_PAYMENT")
        self.assertEqual(order.payment_status, "PENDING")
        self.assertEqual(order.total_minor, 30000)
        delivery = order.supplier_orders.get().delivery
        self.assertEqual(delivery.address_snapshot["address_line1"], "99 Project Road")
        self.product.inventory.refresh_from_db()
        self.assertEqual(self.product.inventory.available_quantity, 7)
        self.assertEqual(self.product.inventory.reserved_quantity, 3)
        self.assertEqual(get_active_cart(self.customer.customer_profile).items.count(), 0)
        self.assertContains(response, order.order_number)
        self.assertContains(response, "Payment has not yet been confirmed")

    def test_same_browser_submission_key_returns_one_order(self):
        add_item(customer=self.customer.customer_profile, product=self.product, quantity=2)
        self._checkout_page()
        payload = self._submit_data()
        first = self.client.post("/shop/checkout/submit/", payload)
        second = self.client.post("/shop/checkout/submit/", payload)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(MasterOrder.objects.filter(customer=self.customer.customer_profile).count(), 1)
        self.product.inventory.refresh_from_db()
        self.assertEqual(self.product.inventory.reserved_quantity, 2)

    def test_foreign_address_empty_cart_and_changed_price_are_rejected(self):
        self._checkout_page()
        other = register_customer(email="foreign-checkout@example.com", password1="Strongpass123!", full_name="Foreign", phone="9")
        foreign = CustomerAddress.objects.create(customer=other.customer_profile, recipient_name="Foreign", phone="9", address_line1="Foreign St", city="Cebu", province="Cebu", is_default=True)
        response = self.client.post("/shop/checkout/submit/", self._submit_data(foreign))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(MasterOrder.objects.count(), 0)
        add_item(customer=self.customer.customer_profile, product=self.product, quantity=2)
        self._checkout_page()
        old = self.product.prices.get(); old.is_active = False; old.save()
        ProductPrice.objects.create(product=self.product, amount_minor=11000, currency="PHP", starts_at=__import__("django.utils.timezone", fromlist=["now"]).now())
        response = self.client.post("/shop/checkout/submit/", self._submit_data())
        self.assertEqual(response.status_code, 400)
        self.assertEqual(MasterOrder.objects.count(), 0)

    def test_order_confirmation_and_detail_are_customer_scoped(self):
        add_item(customer=self.customer.customer_profile, product=self.product, quantity=2)
        result = checkout(customer=self.customer.customer_profile, idempotency_key="browser-detail")
        order = MasterOrder.objects.get(pk=result["master_order_id"])
        self.assertEqual(self.client.get(f"/shop/orders/{order.pk}/confirmation/").status_code, 200)
        self.assertEqual(self.client.get(f"/shop/orders/{order.pk}/").status_code, 200)
        other = register_customer(email="order-viewer@example.com", password1="Strongpass123!", full_name="Viewer", phone="8")
        self.client.force_login(other)
        self.assertEqual(self.client.get(f"/shop/orders/{order.pk}/confirmation/").status_code, 404)


class ReservationExpiryCommandTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_superuser("admin@expiry.com","Strongpass123!")
        self.customer=register_customer(email="buyer@expiry.com",password1="Strongpass123!",full_name="Buyer",phone="1")
        CustomerAddress.objects.create(customer=self.customer.customer_profile,recipient_name="Buyer",phone="1",address_line1="1 Build St",city="Manila",province="Metro Manila",is_default=True)
        self.owner,self.supplier=register_supplier(email="owner@expiry.com",password1="Strongpass123!",full_name="Owner",phone="1",legal_name="Expiry Legal",display_name="Expiry Supply",business_phone="1")
        self.category=Category.objects.create(name="Expiry Hardware",slug="expiry-hardware")
        self.product=self._product("Nails", "EXP-1", 10)

    def _product(self, name, sku, stock):
        product=create_product(supplier=self.supplier,actor=self.owner,name=name,sku=sku,category=self.category,description="",unit_of_measure="box",minimum_order_quantity=1,amount_minor=1000)
        submit_for_review(product=product,actor=self.owner);moderate_product(product=product,actor=self.admin,approve=True)
        if self.supplier.approval_status != "APPROVED": transition_supplier(supplier=self.supplier,actor=self.admin,status="APPROVED")
        record_movement(inventory_id=product.inventory.id,actor=self.owner,movement_type="RESTOCK",quantity_delta=stock,reason="Opening")
        return product

    def _checkout(self, customer=None, key="expiry-order", products=None):
        customer=customer or self.customer
        for product, quantity in products or [(self.product,2)]: add_item(customer=customer.customer_profile,product=product,quantity=quantity)
        result=checkout(customer=customer.customer_profile,idempotency_key=key)
        return MasterOrder.objects.get(pk=result["master_order_id"])

    def _expire(self, order):
        from django.utils import timezone
        order.supplier_orders.first().inventory_reservations.update(expires_at=timezone.now())

    def _run(self, *args):
        output=StringIO();call_command("expire_reservations",*args,stdout=output);return output.getvalue()

    def test_normal_expiry_and_repeat_do_not_duplicate_release_or_movement(self):
        order=self._checkout();self._expire(order)
        first=self._run();second=self._run()
        order.refresh_from_db();self.product.inventory.refresh_from_db()
        reservation=order.supplier_orders.first().inventory_reservations.get()
        self.assertIn('"orders_processed": 1',first);self.assertIn('"expired_reservations_discovered": 0',second)
        self.assertEqual(order.status,"CANCELLED");self.assertEqual(order.payment_status,"EXPIRED")
        self.assertEqual(reservation.status,"EXPIRED");self.assertEqual(self.product.inventory.available_quantity,10);self.assertEqual(self.product.inventory.reserved_quantity,0)
        self.assertEqual(self.product.inventory.movements.filter(movement_type="RESERVATION_RELEASE").count(),1)

    def test_multiple_reservations_are_released_once(self):
        second=self._product("Bolts", "EXP-2", 8)
        order=self._checkout(products=[(self.product,2),(second,3)]);self._expire(order)
        self._run();order.refresh_from_db();self.product.inventory.refresh_from_db();second.inventory.refresh_from_db()
        self.assertEqual(order.supplier_orders.first().inventory_reservations.filter(status="EXPIRED").count(),2)
        self.assertEqual(self.product.inventory.available_quantity,10);self.assertEqual(second.inventory.available_quantity,8)
        self.assertEqual(self.product.inventory.movements.filter(movement_type="RESERVATION_RELEASE").count(),1)
        self.assertEqual(second.inventory.movements.filter(movement_type="RESERVATION_RELEASE").count(),1)

    def test_dry_run_reports_candidates_without_writing(self):
        order=self._checkout();self._expire(order)
        output=self._run("--dry-run");order.refresh_from_db();self.product.inventory.refresh_from_db()
        self.assertIn('"dry_run": true',output);self.assertIn('"orders_processed": 1',output)
        self.assertEqual(order.status,"PENDING_PAYMENT");self.assertEqual(self.product.inventory.reserved_quantity,2)
        self.assertEqual(order.supplier_orders.first().inventory_reservations.get().status,"ACTIVE")

    def test_already_paid_and_active_reconciliation_orders_are_skipped(self):
        paid=self._checkout(key="paid-skip");self._expire(paid);paid.status="PROCESSING";paid.payment_status="PAID";paid.save(update_fields=["status","payment_status"])
        reconciled_customer=register_customer(email="reconciliation-expiry@example.com",password1="Strongpass123!",full_name="Recon",phone="3")
        CustomerAddress.objects.create(customer=reconciled_customer.customer_profile,recipient_name="Recon",phone="3",address_line1="2 Build St",city="Manila",province="Metro Manila",is_default=True)
        reconciled=self._checkout(customer=reconciled_customer,key="recon-skip");self._expire(reconciled)
        from apps.payments.models import Payment, PaymentReconciliation, WebhookEvent
        payment=Payment.objects.create(master_order=reconciled,internal_reference="PAY-EXP-RECON",provider_code="demo",method_category="EWALLET",amount_minor=reconciled.total_minor,currency="PHP")
        event=WebhookEvent.objects.create(provider_code="demo",provider_event_id="expiry-recon-event",verified=True,raw_body="{}")
        PaymentReconciliation.objects.create(payment=payment,master_order=reconciled,webhook_event=event,provider_code="demo",provider_event_id="expiry-recon-event",amount_minor=payment.amount_minor,currency="PHP")
        output=self._run();paid.refresh_from_db();reconciled.refresh_from_db()
        self.assertIn('"orders_skipped": 2',output);self.assertIn('"reconciliation_cases": 1',output)
        self.assertEqual(paid.status,"PROCESSING");self.assertEqual(reconciled.status,"PENDING_PAYMENT")
        self.assertEqual(paid.supplier_orders.first().inventory_reservations.get().status,"ACTIVE")
        self.assertEqual(reconciled.supplier_orders.first().inventory_reservations.get().status,"ACTIVE")

    def test_one_failed_order_rolls_back_and_other_orders_complete(self):
        failing=self._checkout(key="failing-order");self._expire(failing)
        other=register_customer(email="other-expiry@example.com",password1="Strongpass123!",full_name="Other",phone="4")
        CustomerAddress.objects.create(customer=other.customer_profile,recipient_name="Other",phone="4",address_line1="3 Build St",city="Manila",province="Metro Manila",is_default=True)
        succeeding=self._checkout(customer=other,key="succeeding-order");self._expire(succeeding)
        from apps.orders.management.commands.expire_reservations import release_reservations as real_release
        def fail_one(*,master_order,**kwargs):
            if master_order.pk == failing.pk: raise RuntimeError("simulated release failure")
            return real_release(master_order=master_order,**kwargs)
        with patch("apps.orders.management.commands.expire_reservations.release_reservations",side_effect=fail_one):
            with self.assertRaises(CommandError): self._run()
        failing.refresh_from_db();succeeding.refresh_from_db()
        self.assertEqual(failing.status,"PENDING_PAYMENT");self.assertEqual(succeeding.status,"CANCELLED")
        self.assertEqual(failing.supplier_orders.first().inventory_reservations.get().status,"ACTIVE")
        self.assertEqual(succeeding.supplier_orders.first().inventory_reservations.get().status,"EXPIRED")
