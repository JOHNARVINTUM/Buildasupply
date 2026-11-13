from django.template import Context, Template
from django.test import SimpleTestCase
from django.test import TestCase
from django.contrib.auth import get_user_model
from apps.accounts.services import register_customer, register_supplier


class SharedHeaderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer = register_customer(email="header-customer@example.com", password1="Strongpass123!", full_name="Customer", phone="1")
        cls.owner, cls.supplier = register_supplier(email="header-supplier@example.com", password1="Strongpass123!", full_name="Supplier", phone="1", legal_name="Header Supplies", display_name="Header Supplies", business_phone="1")
        cls.supplier.approval_status = "APPROVED"
        cls.supplier.save()
        cls.admin = get_user_model().objects.create_superuser("header-admin@example.com", "Strongpass123!")

    def check_header(self, path, allowed, forbidden):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, path)
        self.assertContains(response, '<header class="site-header">', count=1)
        header = response.content.decode().split('<header class="site-header">')[1].split('</header>')[0]
        self.assertIn('class="about-nav-link" href="/about/"', header)
        for href in allowed:
            self.assertIn(f'href="{href}"', header)
        for href in forbidden:
            self.assertNotIn(f'href="{href}"', header)
        return header

    def test_visitor_pages_share_the_header(self):
        for path in ("/", "/about/", "/login/", "/register/", "/supplier/register/", "/password-reset/", "/shop/browse/"):
            with self.subTest(path=path):
                self.check_header(path, ["/login/", "/register/"], ["/operations/dashboard/", "/supplier/dashboard/", "/logout/"])

    def test_customer_header_on_customer_and_public_pages(self):
        self.client.force_login(self.customer)
        for path in ("/about/", "/shop/browse/", "/shop/cart/", "/shop/orders/", "/account/addresses/", "/notifications/", "/profile/"):
            with self.subTest(path=path):
                self.check_header(path, ["/shop/cart/", "/shop/orders/", "/profile/", "/logout/"], ["/operations/dashboard/", "/supplier/dashboard/"])
        header = self.check_header("/shop/cart/", [], [])
        self.assertIn('href="/shop/cart/" aria-current="page"', header)

    def test_supplier_header_on_supplier_and_public_pages(self):
        self.client.force_login(self.owner)
        for path in ("/about/", "/supplier/dashboard/", "/supplier/products/", "/supplier/products/create/", "/supplier/wallet/", "/supplier/orders/", "/notifications/", "/profile/"):
            with self.subTest(path=path):
                self.check_header(path, ["/supplier/dashboard/", "/profile/", "/logout/"], ["/operations/dashboard/", "/shop/cart/"])

    def test_admin_header_on_operations_and_public_pages(self):
        self.client.force_login(self.admin)
        for path in ("/about/", "/operations/dashboard/", "/operations/users/", "/operations/suppliers/", "/operations/audit/", "/operations/cod/orders/", "/operations/cod/reconciliations/", "/operations/cod/settlements/", "/notifications/", "/profile/"):
            with self.subTest(path=path):
                self.check_header(path, ["/operations/dashboard/", "/profile/", "/logout/"], ["/supplier/dashboard/", "/shop/cart/"])


class CurrencyFormattingTests(SimpleTestCase):
    def test_php_formats_centavos_as_pesos(self):
        self.assertEqual(Template("{% load currency %}{{ amount|php }}").render(Context({"amount": 125000})), "₱1,250.00")
