from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from apps.customers.models import CustomerProfile
from apps.memberships.models import MembershipTier
from apps.suppliers.models import Supplier, SupplierStaffMembership
from .services import register_supplier, set_supplier_approval

User = get_user_model()

class RegistrationTests(TestCase):
    def test_home_landing_page_is_available_to_visitors(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "home.html")
        self.assertContains(response, "Browse Supplies")

    def test_home_redirects_customers_to_shop(self):
        user = User.objects.create_user("customer-home@example.com", "Strongpass123!")
        self.client.force_login(user)
        self.assertRedirects(self.client.get("/"), "/shop/", fetch_redirect_response=False)

    def test_home_redirects_suppliers_to_supplier_area(self):
        user, _ = register_supplier(email="supplier-home@example.com", password1="Strongpass123!", full_name="Supplier", phone="0917", legal_name="Supplier Legal", display_name="Supplier", business_phone="0917")
        self.client.force_login(user)
        self.assertRedirects(self.client.get("/"), "/supplier/", fetch_redirect_response=False)

    def test_home_redirects_superadmins_to_operations(self):
        user = User.objects.create_superuser("operations-home@example.com", "Strongpass123!")
        self.client.force_login(user)
        self.assertRedirects(self.client.get("/"), "/operations/", fetch_redirect_response=False)

    def test_home_invalid_role_is_logged_out_and_cannot_bypass_authorization(self):
        user = User.objects.create_user("unknown-role@example.com", "Strongpass123!")
        user.primary_role = "UNKNOWN"
        user.save(update_fields=["primary_role"])
        self.client.force_login(user)
        response = self.client.get("/")
        self.assertRedirects(response, reverse("accounts:login"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_existing_and_api_routes_remain_resolvable(self):
        self.assertEqual(self.client.get("/register/").status_code, 200)
        self.assertEqual(self.client.get("/shop/").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/me/").status_code, 403)

    def test_customer_registration_creates_profile_and_standard_membership(self):
        response = self.client.post(reverse("accounts:register"), {"email": " Buyer@example.com ", "first_name": " Buyer ", "last_name": " One ", "phone": "09170000000", "password1": "Strongpass123!", "password2": "Strongpass123!", "accept_terms": "on"}, follow=True)
        self.assertEqual(response.redirect_chain, [(reverse("accounts:registration-success"), 302)])
        user = User.objects.get(email="buyer@example.com")
        self.assertEqual(user.primary_role, "CUSTOMER")
        self.assertTrue(CustomerProfile.objects.filter(user=user).exists())
        self.assertEqual(user.customer_profile.membership_assignments.get().tier.code, "STANDARD")
        self.assertEqual(user.customer_profile.phone, "+639170000000")
        self.assertTrue(hasattr(user, "terms_acceptance"))
        self.assertContains(response, "Account Created Successfully")
    def test_customer_registration_rejects_missing_terms_mismatched_or_duplicate_email(self):
        payload = {"email": "buyer@example.com", "first_name": "Buyer", "last_name": "One", "phone": "09170000000", "password1": "Strongpass123!", "password2": "Differentpass123!"}
        response = self.client.post(reverse("accounts:register"), payload)
        self.assertContains(response, "Passwords do not match")
        payload.update(password2="Strongpass123!", accept_terms="on")
        self.client.post(reverse("accounts:register"), payload)
        response = self.client.post(reverse("accounts:register"), payload)
        self.assertContains(response, "An account already exists for this email")
    def test_supplier_registration_is_pending_and_confirmed_without_login(self):
        payload = {"email": "supplier-form@example.com", "first_name": "Owner", "last_name": "One", "phone": "09170000000", "password1": "Strongpass123!", "password2": "Strongpass123!", "accept_terms": "on", "legal_name": "Supplier Form Legal", "display_name": "Supplier Form", "business_address": "Manila, Philippines", "business_registration_number": "REG-12345", "business_phone": "09170000001"}
        response = self.client.post(reverse("accounts:supplier-register"), payload, follow=True)
        self.assertEqual(response.redirect_chain, [(reverse("accounts:registration-success"), 302)])
        supplier = Supplier.objects.get(email="supplier-form@example.com")
        self.assertEqual(supplier.approval_status, "PENDING_REVIEW")
        self.assertEqual(supplier.business_registration_number, "REG-12345")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "Pending Review")
    def test_supplier_registration_is_pending_and_owner_scoped(self):
        user, supplier = register_supplier(email="owner@example.com", password1="Strongpass123!", full_name="Owner", phone="0917", legal_name="A Supply Inc", display_name="A Supply", business_phone="0917")
        self.assertEqual(supplier.approval_status, "PENDING_REVIEW")
        self.assertEqual(SupplierStaffMembership.objects.get(user=user).role, "OWNER")
    def test_suspended_account_cannot_login(self):
        user = User.objects.create_user("blocked@example.com", "Strongpass123!")
        user.account_status = "SUSPENDED"; user.save()
        response = self.client.post(reverse("accounts:login"), {"username": "blocked@example.com", "password": "Strongpass123!"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
    def test_suspension_terminates_existing_session(self):
        user = User.objects.create_user("session@example.com", "Strongpass123!")
        self.client.force_login(user)
        user.account_status = "SUSPENDED"; user.save()
        self.client.get(reverse("accounts:profile"))
        self.assertNotIn("_auth_user_id", self.client.session)
    def test_password_reset_does_not_enumerate_and_sends_for_active_user(self):
        User.objects.create_user("active@example.com", "Strongpass123!")
        self.client.post(reverse("accounts:password-reset"), {"email": "unknown@example.com"})
        self.assertEqual(len(mail.outbox), 0)
        self.client.post(reverse("accounts:password-reset"), {"email": "active@example.com"})
        self.assertEqual(len(mail.outbox), 1)

class SupplierIsolationTests(TestCase):
    def setUp(self):
        self.a_user, self.a = register_supplier(email="a@example.com", password1="Strongpass123!", full_name="A", phone="1", legal_name="A Legal", display_name="Supplier A", business_phone="1")
        self.b_user, self.b = register_supplier(email="b@example.com", password1="Strongpass123!", full_name="B", phone="2", legal_name="B Legal", display_name="Supplier B", business_phone="2")
        self.client = APIClient(); self.client.force_authenticate(self.a_user)
    def test_direct_uuid_manipulation_is_denied(self):
        response = self.client.get(f"/api/v1/suppliers/{self.b.id}/scope/")
        self.assertEqual(response.status_code, 404)
    def test_unapproved_supplier_cannot_pass_approved_permission(self):
        from .permissions import IsApprovedSupplier
        request = type("Request", (), {"user": self.a_user})()
        self.assertFalse(IsApprovedSupplier().has_permission(request, None))
    def test_superadmin_can_access_supplier_scope(self):
        admin = User.objects.create_superuser("admin@example.com", "Strongpass123!")
        self.client.force_authenticate(admin)
        self.assertEqual(self.client.get(f"/api/v1/suppliers/{self.b.id}/scope/").status_code, 200)
    def test_one_active_supplier_membership_per_user(self):
        with self.assertRaises(Exception): SupplierStaffMembership.objects.create(supplier=self.b, user=self.a_user, role="MANAGER")
