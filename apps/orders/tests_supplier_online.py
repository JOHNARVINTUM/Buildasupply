from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.services import register_customer, register_supplier
from apps.catalog.models import Category
from apps.catalog.services import create_product, moderate_product, submit_for_review, transition_supplier
from apps.carts.services import add_item
from apps.customers.models import CustomerAddress
from apps.inventory.services import record_movement
from apps.orders.services import checkout
from apps.payments.models import Payment
from apps.payments.services import confirm_payment, initiate_payment


User = get_user_model()


class SupplierOnlinePaidBrowserTests(TestCase):
    """Verify that suppliers can fulfill orders only after online payment is verified."""

    def setUp(self):
        admin = User.objects.create_superuser("admin@online-payment.com", "Strongpass123!")
        self.customer = register_customer(
            email="buyer@online-payment.com",
            password1="Strongpass123!",
            full_name="Buyer",
            phone="1",
        )
        CustomerAddress.objects.create(
            customer=self.customer.customer_profile,
            recipient_name="Buyer",
            phone="1",
            address_line1="x",
            city="Manila",
            province="Metro Manila",
            is_default=True,
        )
        owner, supplier = register_supplier(
            email="owner@online-payment.com",
            password1="Strongpass123!",
            full_name="Owner",
            phone="1",
            legal_name="Legal",
            display_name="Supply",
            business_phone="1",
        )
        product = create_product(
            supplier=supplier,
            actor=owner,
            name="Bolt",
            sku="ONLINE-B1",
            category=Category.objects.create(name="Online fasteners", slug="online-fasteners"),
            description="",
            unit_of_measure="box",
            minimum_order_quantity=1,
            amount_minor=5000,
        )
        submit_for_review(product=product, actor=owner)
        moderate_product(product=product, actor=admin, approve=True)
        transition_supplier(supplier=supplier, actor=admin, status="APPROVED")
        record_movement(
            inventory_id=product.inventory.id,
            actor=owner,
            movement_type="RESTOCK",
            quantity_delta=4,
            reason="Opening",
        )
        add_item(customer=self.customer.customer_profile, product=product, quantity=2)
        self.order_id = checkout(
            customer=self.customer.customer_profile,
            idempotency_key="supplier-online-checkout",
        )["master_order_id"]
        from apps.orders.models import MasterOrder

        order = MasterOrder.objects.get(pk=self.order_id)
        result = initiate_payment(
            customer=self.customer.customer_profile,
            order=order,
            provider_code="demo",
            method_category="EWALLET",
            idempotency_key="supplier-online-order",
        )
        payment = Payment.objects.get(pk=result["payment_id"])
        confirm_payment(
            payment=payment,
            provider_event_id="supplier-online-paid",
            event_type="SUCCESS",
            normalized_status="PAID",
        )
        self.supplier_order = payment.master_order.supplier_orders.get()
        self.owner = owner
        self.client.force_login(self.owner)

    def test_paid_online_order_is_visible_to_its_supplier(self):
        dashboard = self.client.get("/supplier/orders/?payment=online")
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, self.supplier_order.master_order.order_number)
        self.assertContains(dashboard, "Paid online")

        detail = self.client.get(f"/supplier/orders/{self.supplier_order.pk}/")
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Payment verified before fulfillment")
        self.assertContains(detail, "Accept online-paid order")

    def test_online_paid_order_uses_the_normal_fulfillment_state_machine(self):
        base_url = f"/supplier/orders/{self.supplier_order.pk}/"
        self.assertRedirects(
            self.client.post(f"{base_url}confirm-online/"), base_url, fetch_redirect_response=False
        )
        self.assertRedirects(
            self.client.post(f"{base_url}prepare/"), base_url, fetch_redirect_response=False
        )
        self.assertRedirects(
            self.client.post(f"{base_url}ready/"), base_url, fetch_redirect_response=False
        )
        self.assertRedirects(
            self.client.post(
                f"{base_url}dispatch/",
                {"carrier_name": "Supplier delivery", "tracking_reference": "ONLINE-DEL-1", "notes": "Gate 2"},
            ),
            base_url,
            fetch_redirect_response=False,
        )
        self.assertRedirects(
            self.client.post(f"{base_url}deliver/"), base_url, fetch_redirect_response=False
        )
        self.assertRedirects(
            self.client.post(f"{base_url}complete/"), base_url, fetch_redirect_response=False
        )
        self.supplier_order.refresh_from_db()
        self.assertEqual(self.supplier_order.status, "COMPLETED")

    def test_cod_collection_endpoints_cannot_be_used_for_an_online_paid_order(self):
        response = self.client.post(f"/supplier/orders/{self.supplier_order.pk}/accept/")
        self.assertRedirects(
            response,
            f"/supplier/orders/{self.supplier_order.pk}/",
            fetch_redirect_response=False,
        )
        self.supplier_order.refresh_from_db()
        self.assertEqual(self.supplier_order.status, "PENDING_SUPPLIER")
