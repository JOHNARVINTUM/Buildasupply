from django.contrib.auth import get_user_model
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
