from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from apps.accounts.services import register_customer, register_supplier
from apps.catalog.models import Category
from apps.catalog.services import create_product, moderate_product, submit_for_review, transition_supplier
from apps.inventory.services import record_movement
from .services import add_item, get_active_cart, validate_cart
User=get_user_model()
class CustomerCatalogCartTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_superuser("admin@cart.com","Strongpass123!")
        self.customer=register_customer(email="buyer@cart.com",password1="Strongpass123!",full_name="Buyer",phone="1")
        self.owner,self.supplier=register_supplier(email="owner@cart.com",password1="Strongpass123!",full_name="Owner",phone="1",legal_name="Legal",display_name="A Supply",business_phone="1")
        self.category=Category.objects.create(name="Paint",slug="paint")
        self.product=create_product(supplier=self.supplier,actor=self.owner,name="Wall Paint",sku="P1",category=self.category,description="Interior paint",unit_of_measure="can",minimum_order_quantity=2,amount_minor=125000)
        submit_for_review(product=self.product,actor=self.owner);moderate_product(product=self.product,actor=self.admin,approve=True);transition_supplier(supplier=self.supplier,actor=self.admin,status="APPROVED")
        record_movement(inventory_id=self.product.inventory.id,actor=self.owner,movement_type="RESTOCK",quantity_delta=10,reason="Opening")
    def test_public_catalog_only_shows_purchasable_products(self):
        response=APIClient().get("/api/v1/catalog/products/?q=Wall")
        self.assertEqual(response.status_code,200);self.assertEqual(response.data["count"],1)
        self.supplier.operational_status="INACTIVE";self.supplier.save()
        self.assertEqual(APIClient().get("/api/v1/catalog/products/").data["count"],0)
    def test_cart_moq_price_change_and_customer_isolation(self):
        item=add_item(customer=self.customer.customer_profile,product=self.product,quantity=2)
        cart=get_active_cart(self.customer.customer_profile);self.assertEqual(cart.items.count(),1)
        price=self.product.prices.get();price.is_active=False;price.save()
        from apps.catalog.models import ProductPrice
        from django.utils import timezone
        ProductPrice.objects.create(product=self.product,amount_minor=130000,currency="PHP",starts_at=timezone.now())
        validation=validate_cart(cart);self.assertFalse(validation["valid"]);self.assertEqual(validation["items"][0]["reason"],"PRICE_CHANGED")
        other=register_customer(email="other@cart.com",password1="Strongpass123!",full_name="Other",phone="2")
        client=APIClient();client.force_authenticate(other)
        self.assertEqual(client.patch(f"/api/v1/cart/items/{item.id}/",{"quantity":2}).status_code,404)
    def test_cart_rejects_moq_and_stock_without_reserving(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):add_item(customer=self.customer.customer_profile,product=self.product,quantity=1)
        with self.assertRaises(ValidationError):add_item(customer=self.customer.customer_profile,product=self.product,quantity=11)
        self.product.inventory.refresh_from_db();self.assertEqual(self.product.inventory.reserved_quantity,0)
