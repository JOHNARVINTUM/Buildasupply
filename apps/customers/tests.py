from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.services import register_customer, register_supplier
from apps.orders.services import _address_snapshot

from .models import CustomerAddress


User = get_user_model()


class CustomerAddressViewsTests(TestCase):
    def setUp(self):
        self.customer = register_customer(
            email="buyer-address@example.com", password1="Strongpass123!",
            full_name="Buyer Address", phone="09170000000",
        )
        self.other = register_customer(
            email="other-address@example.com", password1="Strongpass123!",
            full_name="Other Address", phone="09170000001",
        )
        self.client.force_login(self.customer)
        self.payload = {
            "recipient_name": "Buyer Address", "phone": "09170000000",
            "address_line1": "1 Build Street", "address_line2": "Unit 2",
            "barangay": "San Antonio", "city": "Manila", "province": "Metro Manila",
            "postal_code": "1000", "country": "ph",
        }

    def _create(self, **overrides):
        data = {**self.payload, **overrides}
        return CustomerAddress.objects.create(customer=self.customer.customer_profile, **data)

    def test_list_shows_only_owned_addresses_and_customer_navigation(self):
        mine = self._create(is_default=True)
        other = CustomerAddress.objects.create(
            customer=self.other.customer_profile, recipient_name="Other", phone="1",
            address_line1="2 Other St", city="Cebu", province="Cebu", is_default=True,
        )
        response = self.client.get(reverse("customers:address-list"))
        self.assertContains(response, mine.address_line1)
        self.assertNotContains(response, other.address_line1)
        self.assertContains(response, "Add new address")
        self.assertContains(response, "Manage addresses")

    def test_create_valid_address_normalizes_country_and_makes_first_default(self):
        response = self.client.post(reverse("customers:address-create"), self.payload, follow=True)
        self.assertRedirects(response, reverse("customers:address-list"))
        address = CustomerAddress.objects.get(customer=self.customer.customer_profile)
        self.assertTrue(address.is_default)
        self.assertEqual(address.country, "PH")
        self.assertContains(response, "Delivery address added")

    def test_create_requires_model_required_fields_and_allows_multiple_addresses(self):
        response = self.client.post(reverse("customers:address-create"), {**self.payload, "city": ""})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required")
        self.assertEqual(CustomerAddress.objects.count(), 0)
        self.client.post(reverse("customers:address-create"), self.payload)
        self.client.post(reverse("customers:address-create"), {**self.payload, "address_line1": "2 Build Street"})
        self.assertEqual(CustomerAddress.objects.filter(customer=self.customer.customer_profile).count(), 2)

    def test_create_marked_default_replaces_existing_default(self):
        first = self._create(is_default=True)
        response = self.client.post(reverse("customers:address-create"), {**self.payload, "address_line1": "2 Build Street", "is_default": "on"})
        self.assertEqual(response.status_code, 302)
        first.refresh_from_db()
        second = CustomerAddress.objects.get(address_line1="2 Build Street")
        self.assertFalse(first.is_default)
        self.assertTrue(second.is_default)

    def test_edit_updates_owned_address_and_rejects_invalid_or_foreign_address(self):
        address = self._create(is_default=True)
        response = self.client.post(reverse("customers:address-edit", args=[address.pk]), {**self.payload, "city": "Quezon City", "is_default": "on"}, follow=True)
        self.assertRedirects(response, reverse("customers:address-list"))
        address.refresh_from_db()
        self.assertEqual(address.city, "Quezon City")
        response = self.client.post(reverse("customers:address-edit", args=[address.pk]), {**self.payload, "province": ""})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required")
        foreign = CustomerAddress.objects.create(customer=self.other.customer_profile, recipient_name="Other", phone="1", address_line1="Other", city="Cebu", province="Cebu", is_default=True)
        self.assertEqual(self.client.get(reverse("customers:address-edit", args=[foreign.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("customers:address-edit", args=[999999])).status_code, 404)

    def test_delete_requires_confirmation_post_reassigns_default_and_keeps_snapshots(self):
        first = self._create(is_default=True)
        second = self._create(address_line1="2 Build Street", is_default=False)
        snapshot = _address_snapshot(self.customer.customer_profile)
        self.assertEqual(self.client.get(reverse("customers:address-delete", args=[first.pk])).status_code, 200)
        self.assertTrue(CustomerAddress.objects.filter(pk=first.pk).exists())
        response = self.client.post(reverse("customers:address-delete", args=[first.pk]), follow=True)
        self.assertRedirects(response, reverse("customers:address-list"))
        self.assertFalse(CustomerAddress.objects.filter(pk=first.pk).exists())
        second.refresh_from_db()
        self.assertTrue(second.is_default)
        self.assertEqual(snapshot["address_line1"], "1 Build Street")

    def test_delete_and_default_actions_enforce_ownership_and_post_method(self):
        mine = self._create(is_default=True)
        foreign = CustomerAddress.objects.create(customer=self.other.customer_profile, recipient_name="Other", phone="1", address_line1="Other", city="Cebu", province="Cebu", is_default=True)
        self.assertEqual(self.client.post(reverse("customers:address-delete", args=[foreign.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("customers:address-set-default", args=[foreign.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("customers:address-set-default", args=[mine.pk])).status_code, 404)

    def test_set_default_is_repeatable_and_leaves_exactly_one_default(self):
        first = self._create(is_default=True)
        second = self._create(address_line1="2 Build Street", is_default=False)
        url = reverse("customers:address-set-default", args=[second.pk])
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(self.client.post(url).status_code, 302)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_default)
        self.assertTrue(second.is_default)
        self.assertEqual(CustomerAddress.objects.filter(customer=self.customer.customer_profile, is_default=True).count(), 1)

    def test_non_customer_is_forbidden(self):
        supplier, _ = register_supplier(
            email="supplier-address@example.com", password1="Strongpass123!", full_name="Supplier",
            phone="09170000002", legal_name="Supplier Legal", display_name="Supplier",
            business_phone="09170000002",
        )
        self.client.force_login(supplier)
        self.assertEqual(self.client.get(reverse("customers:address-list")).status_code, 403)
