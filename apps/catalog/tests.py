from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from apps.accounts.services import register_supplier
from apps.suppliers.models import SupplierStaffMembership
from .models import Category, Product
from .services import create_product, moderate_product, submit_for_review, transition_supplier
User=get_user_model()
class CatalogTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_superuser("admin@x.com","Strongpass123!")
        self.owner,self.supplier=register_supplier(email="owner@x.com",password1="Strongpass123!",full_name="Owner",phone="1",legal_name="Legal",display_name="Supply",business_phone="1")
        self.category=Category.objects.create(name="Cement",slug="cement")
        self.product=create_product(supplier=self.supplier,actor=self.owner,name="Portland",sku="C-1",category=self.category,description="",unit_of_measure="bag",minimum_order_quantity=1,amount_minor=30000)
    def test_product_requires_approval_and_active_stock_to_purchase(self):
        from .services import is_product_purchasable
        self.assertFalse(is_product_purchasable(self.product)); submit_for_review(product=self.product,actor=self.owner); moderate_product(product=self.product,actor=self.admin,approve=True); transition_supplier(supplier=self.supplier,actor=self.admin,status="APPROVED")
        self.assertFalse(is_product_purchasable(self.product))
    def test_supplier_cannot_approve_own_product_api(self):
        submit_for_review(product=self.product,actor=self.owner); client=APIClient();client.force_authenticate(self.owner)
        self.assertEqual(client.post(f"/api/v1/products/{self.product.id}/approve/").status_code,404)
    def test_catalog_manager_can_create_own_but_not_other_product(self):
        manager=User.objects.create_user("catalog@x.com","Strongpass123!",primary_role="SUPPLIER")
        SupplierStaffMembership.objects.create(supplier=self.supplier,user=manager,role="CATALOG_MANAGER")
        client=APIClient();client.force_authenticate(manager)
        response=client.post("/api/v1/products/",{"name":"Sand","sku":"S-1","category":str(self.category.id),"unit_of_measure":"bag","amount_minor":100})
        self.assertEqual(response.status_code,201)
class InventoryTests(TestCase):
    def setUp(self):
        self.user,self.supplier=register_supplier(email="i@x.com",password1="Strongpass123!",full_name="I",phone="1",legal_name="Legal",display_name="Supply I",business_phone="1")
        self.product=create_product(supplier=self.supplier,actor=self.user,name="Steel",sku="ST1",category=Category.objects.create(name="Steel",slug="steel"),description="",unit_of_measure="pc",minimum_order_quantity=1,amount_minor=1)
    def test_stock_updates_are_journaled_and_nonnegative(self):
        from apps.inventory.services import record_movement
        movement=record_movement(inventory_id=self.product.inventory.id,actor=self.user,movement_type="RESTOCK",quantity_delta=5,reason="Opening count")
        self.product.inventory.refresh_from_db();self.assertEqual(self.product.inventory.available_quantity,5);self.assertEqual(movement.quantity_delta,5)
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):record_movement(inventory_id=self.product.inventory.id,actor=self.user,movement_type="DAMAGE",quantity_delta=-6,reason="Damage")
