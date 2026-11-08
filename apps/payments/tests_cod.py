from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.services import register_customer, register_supplier
from apps.catalog.models import Category
from apps.catalog.services import create_product, moderate_product, submit_for_review, transition_supplier
from apps.carts.services import add_item
from apps.customers.models import CustomerAddress
from apps.inventory.services import record_movement
from apps.orders.services import checkout
from apps.orders.models import MasterOrder
from apps.wallets.models import SettlementRecord
from .models import CODCollection, CODCommitment
from .services import PaymentFailure, accept_cod_supplier_order, confirm_cod_receipt, record_cod_collection, select_cod

User=get_user_model()

class CODBackendTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_superuser("admin@cod.com","Strongpass123!")
        self.customer=register_customer(email="buyer@cod.com",password1="Strongpass123!",full_name="Buyer",phone="1")
        CustomerAddress.objects.create(customer=self.customer.customer_profile,recipient_name="Buyer",phone="1",address_line1="x",city="Manila",province="Metro",is_default=True)
        self.owner,self.supplier=register_supplier(email="owner@cod.com",password1="Strongpass123!",full_name="Owner",phone="1",legal_name="COD Legal",display_name="COD Supply",business_phone="1")
        product=create_product(supplier=self.supplier,actor=self.owner,name="COD Bolt",sku="COD-1",category=Category.objects.create(name="COD Cat",slug="cod-cat"),description="",unit_of_measure="pc",minimum_order_quantity=1,amount_minor=5000)
        submit_for_review(product=product,actor=self.owner);moderate_product(product=product,actor=self.admin,approve=True);transition_supplier(supplier=self.supplier,actor=self.admin,status="APPROVED");record_movement(inventory_id=product.inventory.id,actor=self.owner,movement_type="RESTOCK",quantity_delta=3,reason="Open")
        add_item(customer=self.customer.customer_profile,product=product,quantity=2);result=checkout(customer=self.customer.customer_profile,idempotency_key="cod-checkout");self.order=MasterOrder.objects.get(pk=result["master_order_id"]);self.so=self.order.supplier_orders.get();self.product=product

    def test_selection_is_idempotent_and_protected_from_expiry(self):
        first=select_cod(customer=self.customer.customer_profile,order=self.order);second=select_cod(customer=self.customer.customer_profile,order=self.order)
        self.assertEqual(first.id,second.id);self.order.refresh_from_db();self.assertEqual(self.order.payment_status,"COD_PENDING")
        from django.core.management import call_command
        from django.utils import timezone
        self.so.inventory_reservations.update(expires_at=timezone.now());call_command("expire_reservations")
        self.so.refresh_from_db();self.assertEqual(self.so.inventory_reservations.get().status,"ACTIVE")

    def test_collection_and_receipt_are_independent_then_create_pending_earnings(self):
        select_cod(customer=self.customer.customer_profile,order=self.order);accept_cod_supplier_order(supplier_order=self.so,actor=self.owner)
        self.so.status="DELIVERED";self.so.save(update_fields=["status"])
        receipt=confirm_cod_receipt(supplier_order=self.so,customer=self.customer.customer_profile)
        self.assertIsNotNone(receipt);self.assertEqual(SettlementRecord.objects.count(),0)
        collection=record_cod_collection(supplier_order=self.so,actor=self.owner,amount_minor=self.so.total_minor,currency="PHP",collection_reference="cash-1")
        duplicate=record_cod_collection(supplier_order=self.so,actor=self.owner,amount_minor=self.so.total_minor,currency="PHP",collection_reference="cash-1")
        self.so.refresh_from_db();self.product.inventory.refresh_from_db();self.assertEqual(collection.id,duplicate.id);self.assertEqual(self.so.status,"COMPLETED");self.assertEqual(SettlementRecord.objects.count(),1);self.assertEqual(self.product.inventory.sold_quantity,2)

    def test_permissions_and_collection_validation(self):
        other=register_customer(email="other@cod.com",password1="Strongpass123!",full_name="Other",phone="2")
        with self.assertRaises(Exception):select_cod(customer=other.customer_profile,order=self.order)
        select_cod(customer=self.customer.customer_profile,order=self.order)
        with self.assertRaises(Exception):accept_cod_supplier_order(supplier_order=self.so,actor=self.customer)
        accept_cod_supplier_order(supplier_order=self.so,actor=self.owner)
        with self.assertRaises(PaymentFailure):record_cod_collection(supplier_order=self.so,actor=self.owner,amount_minor=self.so.total_minor,currency="PHP",collection_reference="early")


class MultiSupplierCODTests(CODBackendTests):
    def setUp(self):
        super().setUp()
        self.owner_b,self.supplier_b=register_supplier(email="owner-b@cod.com",password1="Strongpass123!",full_name="Owner B",phone="8",legal_name="COD Legal B",display_name="COD Supply B",business_phone="8")
        product_b=create_product(supplier=self.supplier_b,actor=self.owner_b,name="COD Pipe",sku="COD-B",category=self.product.category,description="",unit_of_measure="pc",minimum_order_quantity=1,amount_minor=7000)
        submit_for_review(product=product_b,actor=self.owner_b);moderate_product(product=product_b,actor=self.admin,approve=True);transition_supplier(supplier=self.supplier_b,actor=self.admin,status="APPROVED");record_movement(inventory_id=product_b.inventory.id,actor=self.owner_b,movement_type="RESTOCK",quantity_delta=3,reason="Open")
        customer=register_customer(email="multi@cod.com",password1="Strongpass123!",full_name="Multi",phone="9");CustomerAddress.objects.create(customer=customer.customer_profile,recipient_name="Multi",phone="9",address_line1="x",city="Manila",province="Metro",is_default=True)
        add_item(customer=customer.customer_profile,product=self.product,quantity=1);add_item(customer=customer.customer_profile,product=product_b,quantity=1);result=checkout(customer=customer.customer_profile,idempotency_key="multi-cod")
        self.customer_multi=customer;self.order_multi=MasterOrder.objects.get(pk=result["master_order_id"]);self.a=self.order_multi.supplier_orders.get(supplier=self.supplier);self.b=self.order_multi.supplier_orders.get(supplier=self.supplier_b);self.product_b=product_b

    def test_supplier_orders_complete_and_settle_independently(self):
        select_cod(customer=self.customer_multi.customer_profile,order=self.order_multi)
        accept_cod_supplier_order(supplier_order=self.a,actor=self.owner);accept_cod_supplier_order(supplier_order=self.b,actor=self.owner_b)
        self.a.status="DELIVERED";self.a.save(update_fields=["status"])
        record_cod_collection(supplier_order=self.a,actor=self.owner,amount_minor=self.a.total_minor,currency="PHP",collection_reference="a-cash")
        confirm_cod_receipt(supplier_order=self.a,customer=self.customer_multi.customer_profile)
        self.a.refresh_from_db();self.b.refresh_from_db();self.product.inventory.refresh_from_db();self.product_b.inventory.refresh_from_db()
        self.assertEqual(self.a.status,"COMPLETED");self.assertEqual(self.b.status,"CONFIRMED");self.assertEqual(self.product.inventory.sold_quantity,1);self.assertEqual(self.product_b.inventory.sold_quantity,0);self.assertEqual(self.product_b.inventory.reserved_quantity,1)
        from apps.wallets.services import release_settlement
        settlement=self.a.settlement;settlement=release_settlement(settlement);self.assertEqual(settlement.status,"RELEASED");self.assertFalse(hasattr(self.b,"settlement"))

    def test_cross_supplier_access_and_dispute_hold_are_enforced(self):
        select_cod(customer=self.customer_multi.customer_profile,order=self.order_multi)
        with self.assertRaises(Exception):accept_cod_supplier_order(supplier_order=self.b,actor=self.owner)
        accept_cod_supplier_order(supplier_order=self.a,actor=self.owner);self.a.status="DELIVERED";self.a.save(update_fields=["status"])
        with self.assertRaises(Exception):record_cod_collection(supplier_order=self.a,actor=self.owner_b,amount_minor=self.a.total_minor,currency="PHP",collection_reference="bad")
