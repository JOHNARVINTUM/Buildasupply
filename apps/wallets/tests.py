from django.contrib.auth import get_user_model
from django.test import SimpleTestCase,TestCase
from apps.accounts.services import register_customer,register_supplier
from apps.catalog.models import Category
from apps.catalog.services import create_product,moderate_product,submit_for_review,transition_supplier
from apps.carts.services import add_item
from apps.customers.models import CustomerAddress
from apps.inventory.services import record_movement
from apps.orders.services import checkout,transition_supplier_order
from apps.payments.services import confirm_payment,initiate_payment
from apps.payments.models import Payment
from apps.payouts.models import PayoutMethod
from apps.payouts.services import approve_payout,complete_payout,request_payout
from apps.core.templatetags.currency import php
from .services import accept_online_payment_earnings,balances,release_settlement
User=get_user_model()
class CurrencyTemplateFilterTests(SimpleTestCase):
    def test_minor_units_are_formatted_as_php_once(self):
        self.assertEqual(php(24000000),"₱240,000.00")
        self.assertEqual(php(9000000),"₱90,000.00")
        self.assertEqual(php(5000000),"₱50,000.00")
        self.assertEqual(php(0),"₱0.00")
class WalletTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_superuser("admin@wallet.com","Strongpass123!");self.customer=register_customer(email="buyer@wallet.com",password1="Strongpass123!",full_name="Buyer",phone="1");CustomerAddress.objects.create(customer=self.customer.customer_profile,recipient_name="Buyer",phone="1",address_line1="x",city="Manila",province="Metro",is_default=True);self.owner,self.supplier=register_supplier(email="owner@wallet.com",password1="Strongpass123!",full_name="Owner",phone="1",legal_name="Legal",display_name="Supply",business_phone="1");p=create_product(supplier=self.supplier,actor=self.owner,name="Pipe",sku="P1",category=Category.objects.create(name="Plumbing",slug="plumbing"),description="",unit_of_measure="pc",minimum_order_quantity=1,amount_minor=10000);submit_for_review(product=p,actor=self.owner);moderate_product(product=p,actor=self.admin,approve=True);transition_supplier(supplier=self.supplier,actor=self.admin,status="APPROVED");record_movement(inventory_id=p.inventory.id,actor=self.owner,movement_type="RESTOCK",quantity_delta=3,reason="Open");add_item(customer=self.customer.customer_profile,product=p,quantity=2);order=checkout(customer=self.customer.customer_profile,idempotency_key="c");from apps.orders.models import MasterOrder;payment=initiate_payment(customer=self.customer.customer_profile,order=MasterOrder.objects.get(pk=order["master_order_id"]),provider_code="demo",method_category="EWALLET",idempotency_key="p");self.payment=Payment.objects.get(pk=payment["payment_id"])
    def test_payment_posts_pending_then_settlement_releases_once(self):
        confirm_payment(payment=self.payment,provider_event_id="wallet-event",event_type="SUCCESS",normalized_status="PAID");wallet=self.supplier.wallets.get();self.assertEqual(balances(wallet)["pending"],20000);settlement=wallet.settlements.get();settlement.supplier_order.status="COMPLETED";settlement.supplier_order.save();release_settlement(settlement);wallet.refresh_from_db();self.assertEqual(balances(wallet)["pending"],0);self.assertEqual(balances(wallet)["available"],20000);release_settlement(settlement);self.assertEqual(wallet.entries.filter(entry_type="SETTLEMENT").count(),2)
    def test_online_sale_becomes_lifetime_earned_only_after_supplier_acceptance(self):
        confirm_payment(payment=self.payment,provider_event_id="wallet-acceptance",event_type="SUCCESS",normalized_status="PAID");wallet=self.supplier.wallets.get();supplier_order=self.payment.master_order.supplier_orders.get()
        self.assertEqual(balances(wallet)["pending"],20000);self.assertEqual(balances(wallet)["lifetime_earned"],0)
        sale=wallet.entries.get(entry_type="SALE");self.assertEqual(sale.status,"RESERVED")
        transition_supplier_order(supplier_order=supplier_order,actor=self.owner,next_status="CONFIRMED")
        self.assertEqual(balances(wallet)["pending"],20000);self.assertEqual(balances(wallet)["lifetime_earned"],20000)
        sale.refresh_from_db();self.assertEqual(sale.status,"POSTED")
        accept_online_payment_earnings(supplier_order,actor=self.owner)
        self.assertEqual(balances(wallet)["lifetime_earned"],20000);self.assertEqual(wallet.entries.filter(entry_type="SALE").count(),1)
    def test_wallet_page_formats_centavos_and_pending_label(self):
        confirm_payment(payment=self.payment,provider_event_id="wallet-display",event_type="SUCCESS",normalized_status="PAID");self.client.force_login(self.owner)
        response=self.client.get("/supplier/wallet/");self.assertEqual(response.status_code,200);self.assertContains(response,"₱200.00");self.assertContains(response,"₱0.00");self.assertContains(response,"Pending...")
    def test_payout_reserves_and_failure_restores_available(self):
        confirm_payment(payment=self.payment,provider_event_id="wallet-event2",event_type="SUCCESS",normalized_status="PAID");wallet=self.supplier.wallets.get();settlement=wallet.settlements.get();settlement.supplier_order.status="COMPLETED";settlement.supplier_order.save();release_settlement(settlement);method=PayoutMethod.objects.create(wallet=wallet,method_type="BANK",masked_destination="****1234",token_reference="token",is_preferred=True);payout=request_payout(wallet,method,5000,self.owner,"po");approve_payout(payout,self.admin);self.assertEqual(balances(wallet)["available"],15000);complete_payout(payout,failed=True);self.assertEqual(balances(wallet)["available"],20000)
