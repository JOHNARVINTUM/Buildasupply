from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.test import TestCase
from unittest.mock import patch
from rest_framework.test import APIClient
from apps.accounts.services import register_customer, register_supplier
from apps.catalog.models import Category
from apps.catalog.services import create_product, moderate_product, submit_for_review, transition_supplier, update_product, update_product_price
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
    def test_approved_supplier_product_is_published_and_remains_visible_after_edit(self):
        product=create_product(supplier=self.supplier,actor=self.owner,name="Primer",sku="P2",category=self.category,description="Base coat",unit_of_measure="can",minimum_order_quantity=1,amount_minor=20000,publish_for_approved_supplier=True)
        self.assertEqual(product.status,"APPROVED")
        record_movement(inventory_id=product.inventory.id,actor=self.owner,movement_type="RESTOCK",quantity_delta=3,reason="Opening")
        self.assertEqual(APIClient().get("/api/v1/catalog/products/?q=Primer").data["count"],1)
        update_product(product=product,actor=self.owner,description="Updated base coat")
        update_product_price(product=product,actor=self.owner,amount_minor=21000)
        product.refresh_from_db()
        self.assertEqual(product.status,"APPROVED")
        response=APIClient().get("/api/v1/catalog/products/?q=Primer")
        self.assertEqual(response.data["count"],1)
        self.assertEqual(response.data["results"][0]["price_minor"],21000)
    def test_catalog_api_reports_database_failures_instead_of_an_empty_result(self):
        with patch("apps.carts.api_views.customer_catalog_queryset",side_effect=DatabaseError("offline")):
            response=APIClient().get("/api/v1/catalog/products/")
        self.assertEqual(response.status_code,503)
        self.assertIn("temporarily unavailable",response.data["detail"])
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


class CartBrowserWorkflowTests(CustomerCatalogCartTests):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.customer)

    def _add_url(self, product=None):
        return f"/shop/products/{(product or self.product).id}/add/"

    def test_product_detail_adds_product_and_existing_item_does_not_duplicate(self):
        response = self.client.get(f"/shop/products/{self.product.id}/")
        self.assertContains(response, "Add to cart")
        response = self.client.post(self._add_url(), {"quantity": 2}, follow=True)
        self.assertRedirects(response, "/shop/cart/")
        cart = get_active_cart(self.customer.customer_profile)
        self.assertEqual(cart.items.count(), 1)
        response = self.client.post(self._add_url(), {"quantity": 4})
        self.assertEqual(response.status_code, 302)
        item = cart.items.get()
        self.assertEqual(item.quantity, 4)

    def test_browse_distinguishes_a_catalog_failure_from_an_empty_catalog(self):
        with patch("apps.carts.views.customer_catalog_queryset",side_effect=DatabaseError("offline")):
            response=self.client.get("/shop/browse/")
        self.assertEqual(response.status_code,503)
        self.assertContains(response,"We couldn't load the supplies.",status_code=503)
        self.assertNotContains(response,"0 products shown",status_code=503)
        self.assertNotContains(response,"No supplies are currently available",status_code=503)

    def test_add_to_cart_rejects_invalid_moq_and_stock(self):
        response = self.client.post(self._add_url(), {"quantity": 1})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "minimum order quantity", status_code=400)
        response = self.client.post(self._add_url(), {"quantity": 11})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "no longer available", status_code=400)
        self.assertEqual(get_active_cart(self.customer.customer_profile).items.count(), 0)

    def test_cart_update_remove_and_empty_state(self):
        item = add_item(customer=self.customer.customer_profile, product=self.product, quantity=2)
        update_url = f"/shop/cart/items/{item.pk}/update/"
        response = self.client.post(update_url, {"quantity": 5}, follow=True)
        self.assertRedirects(response, "/shop/cart/")
        item.refresh_from_db()
        self.assertEqual(item.quantity, 5)
        response = self.client.post(update_url, {"quantity": 1}, follow=True)
        self.assertContains(response, "minimum order quantity")
        item.refresh_from_db()
        self.assertEqual(item.quantity, 5)
        remove_url = f"/shop/cart/items/{item.pk}/remove/"
        self.assertEqual(self.client.get(remove_url).status_code, 404)
        response = self.client.post(remove_url, follow=True)
        self.assertContains(response, "Your cart is empty")
        self.assertFalse(get_active_cart(self.customer.customer_profile).items.exists())

    def test_cart_groups_multiple_suppliers_and_displays_totals(self):
        owner, supplier = register_supplier(email="owner-two@cart.com", password1="Strongpass123!", full_name="Owner Two", phone="3", legal_name="Legal Two", display_name="B Supply", business_phone="3")
        second = create_product(supplier=supplier, actor=owner, name="Primer", sku="P2", category=self.category, description="", unit_of_measure="can", minimum_order_quantity=1, amount_minor=20000)
        submit_for_review(product=second, actor=owner); moderate_product(product=second, actor=self.admin, approve=True); transition_supplier(supplier=supplier, actor=self.admin, status="APPROVED")
        record_movement(inventory_id=second.inventory.id, actor=owner, movement_type="RESTOCK", quantity_delta=3, reason="Opening")
        add_item(customer=self.customer.customer_profile, product=self.product, quantity=2)
        add_item(customer=self.customer.customer_profile, product=second, quantity=1)
        response = self.client.get("/shop/cart/")
        self.assertEqual(len(response.context["supplier_groups"]), 2)
        self.assertContains(response, "A Supply")
        self.assertContains(response, "B Supply")
        self.assertContains(response, "Cart total")

    def test_cart_validation_warns_for_price_and_availability_changes(self):
        add_item(customer=self.customer.customer_profile, product=self.product, quantity=2)
        price = self.product.prices.get()
        price.is_active = False
        price.save()
        from apps.catalog.models import ProductPrice
        from django.utils import timezone
        ProductPrice.objects.create(product=self.product, amount_minor=130000, currency="PHP", starts_at=timezone.now())
        response = self.client.get("/shop/cart/")
        self.assertContains(response, "price changed")
        self.assertNotContains(response, "Proceed to checkout")
        self.supplier.operational_status = "INACTIVE"
        self.supplier.save()
        response = self.client.get("/shop/cart/")
        self.assertContains(response, "supplier is not currently available")

    def test_cart_actions_are_customer_owned_and_require_customer_role(self):
        item = add_item(customer=self.customer.customer_profile, product=self.product, quantity=2)
        other = register_customer(email="browser-other@cart.com", password1="Strongpass123!", full_name="Other", phone="4")
        self.client.force_login(other)
        self.assertEqual(self.client.post(f"/shop/cart/items/{item.pk}/update/", {"quantity": 2}).status_code, 404)
        self.assertEqual(self.client.post(f"/shop/cart/items/{item.pk}/remove/").status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.post(self._add_url(), {"quantity": 2}).status_code, 302)
        supplier_user, _ = register_supplier(email="browser-supplier@cart.com", password1="Strongpass123!", full_name="Supplier", phone="5", legal_name="Browser Supplier", display_name="Browser Supplier", business_phone="5")
        self.client.force_login(supplier_user)
        self.assertEqual(self.client.post(self._add_url(), {"quantity": 2}).status_code, 403)
