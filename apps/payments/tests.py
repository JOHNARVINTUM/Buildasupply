import hashlib,hmac,json,os
os.environ.setdefault("BUILTASUPPLY_DEMO_WEBHOOK_SECRET", "test-demo-webhook-secret")
from django.contrib.auth import get_user_model
from django.test import TestCase
from apps.accounts.services import register_customer, register_supplier
from apps.catalog.models import Category
from apps.catalog.services import create_product,moderate_product,submit_for_review,transition_supplier
from apps.carts.services import add_item
from apps.customers.models import CustomerAddress
from apps.inventory.services import record_movement
from apps.orders.services import checkout
from .models import Payment
from .services import PaymentFailure, confirm_payment, create_refund, initiate_payment, process_webhook
User=get_user_model()
class PaymentTests(TestCase):
    def setUp(self):
        admin=User.objects.create_superuser("admin@payment.com","Strongpass123!");self.customer=register_customer(email="buyer@payment.com",password1="Strongpass123!",full_name="Buyer",phone="1");CustomerAddress.objects.create(customer=self.customer.customer_profile,recipient_name="Buyer",phone="1",address_line1="x",city="Manila",province="Metro",is_default=True)
        owner,supplier=register_supplier(email="owner@payment.com",password1="Strongpass123!",full_name="Owner",phone="1",legal_name="Legal",display_name="Supply",business_phone="1");p=create_product(supplier=supplier,actor=owner,name="Bolt",sku="B1",category=Category.objects.create(name="Fasteners",slug="fasteners"),description="",unit_of_measure="box",minimum_order_quantity=1,amount_minor=5000);submit_for_review(product=p,actor=owner);moderate_product(product=p,actor=admin,approve=True);transition_supplier(supplier=supplier,actor=admin,status="APPROVED");record_movement(inventory_id=p.inventory.id,actor=owner,movement_type="RESTOCK",quantity_delta=4,reason="Opening");add_item(customer=self.customer.customer_profile,product=p,quantity=2);self.order_id=checkout(customer=self.customer.customer_profile,idempotency_key="checkout") ["master_order_id"];self.product=p
    def _payment(self):
        from apps.orders.models import MasterOrder
        return initiate_payment(customer=self.customer.customer_profile,order=MasterOrder.objects.get(pk=self.order_id),provider_code="demo",method_category="EWALLET",idempotency_key="pay-1")
    def test_webhook_consumes_reservation_once(self):
        result=self._payment();payment=Payment.objects.get(pk=result["payment_id"]);body=json.dumps({"event_id":"evt-1","provider_reference":payment.provider_reference,"status":"SUCCESS"}).encode();sig=hmac.new(os.environ["BUILTASUPPLY_DEMO_WEBHOOK_SECRET"].encode(),body,hashlib.sha256).hexdigest()
        self.assertFalse(process_webhook(provider_code="demo",raw_body=body,headers={"X-Builtasupply-Signature":sig})["duplicate"]);self.assertTrue(process_webhook(provider_code="demo",raw_body=body,headers={"X-Builtasupply-Signature":sig})["duplicate"])
        payment.refresh_from_db();self.product.inventory.refresh_from_db();self.assertEqual(payment.status,"PAID");self.assertEqual(self.product.inventory.reserved_quantity,0);self.assertEqual(self.product.inventory.sold_quantity,2);self.assertEqual(self.product.inventory.movements.filter(movement_type="SALE").count(),1)
    def test_invalid_signature_and_payment_idempotency(self):
        first=self._payment();second=self._payment();self.assertTrue(second["idempotent"])
        with self.assertRaises(PaymentFailure):process_webhook(provider_code="demo",raw_body=b'{}',headers={"X-Builtasupply-Signature":"bad"})
    def test_refund_allocation_and_over_refund_blocked(self):
        result=self._payment();payment=Payment.objects.get(pk=result["payment_id"]);confirm_payment(payment=payment,provider_event_id="evt-refund",event_type="SUCCESS",normalized_status="PAID");payment.refresh_from_db();so=payment.master_order.supplier_orders.first();item=so.items.first()
        refund=create_refund(payment=payment,actor=self.customer,allocations=[{"supplier_order":so,"order_item":item,"amount_minor":1000}],idempotency_key="refund-1",reason="Test")
        self.assertEqual(refund.amount_minor,1000)
        with self.assertRaises(PaymentFailure):create_refund(payment=payment,actor=self.customer,allocations=[{"supplier_order":so,"order_item":item,"amount_minor":10000}],idempotency_key="refund-2",reason="Test")
