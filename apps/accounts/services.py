from django.db import transaction
from apps.audit.services import log_action
from apps.customers.models import CustomerProfile
from apps.memberships.models import MembershipAssignment, MembershipTier
from apps.suppliers.models import Supplier, SupplierStaffMembership
from .models import TermsAcceptance, User
TERMS_VERSION = "2026-10"
PRIVACY_VERSION = "2026-10"

def _full_name(first_name="", last_name="", full_name=""):
    return " ".join(part for part in [first_name.strip(), last_name.strip()] if part) or full_name.strip()
@transaction.atomic
def register_customer(*, email, password1, phone, first_name="", last_name="", full_name="", accept_terms=True, **_):
    if not accept_terms: raise ValueError("Terms acceptance is required.")
    full_name = _full_name(first_name, last_name, full_name)
    if not full_name: raise ValueError("A customer name is required.")
    user = User.objects.create_user(email=email, password=password1, primary_role="CUSTOMER")
    customer = CustomerProfile.objects.create(user=user, full_name=full_name, phone=phone)
    TermsAcceptance.objects.create(user=user, terms_version=TERMS_VERSION, privacy_version=PRIVACY_VERSION)
    tier = MembershipTier.objects.filter(code="STANDARD", is_active=True).first()
    if tier: MembershipAssignment.objects.create(customer=customer, tier=tier)
    log_action(actor=user, action="USER_CREATED", target=user); return user
@transaction.atomic
def register_supplier(*, email, password1, phone, legal_name, display_name, business_phone, first_name="", last_name="", full_name="", business_address="", business_registration_number=None, accept_terms=True, **_):
    if not accept_terms: raise ValueError("Terms acceptance is required.")
    contact_name = _full_name(first_name, last_name, full_name)
    if not contact_name: raise ValueError("A supplier contact name is required.")
    user = User.objects.create_user(email=email, password=password1, primary_role="SUPPLIER")
    supplier = Supplier.objects.create(legal_name=legal_name, display_name=display_name, email=email, phone=business_phone, contact_name=contact_name, business_address=business_address, business_registration_number=business_registration_number)
    SupplierStaffMembership.objects.create(supplier=supplier, user=user, role="OWNER")
    TermsAcceptance.objects.create(user=user, terms_version=TERMS_VERSION, privacy_version=PRIVACY_VERSION)
    log_action(actor=user, action="SUPPLIER_CREATED", target=supplier); return user, supplier
@transaction.atomic
def set_supplier_approval(*, supplier, actor, status, reason=""):
    supplier.approval_status, supplier.review_reason = status, reason
    supplier.save(update_fields=["approval_status", "review_reason", "updated_at"])
    log_action(actor=actor, action=f"SUPPLIER_{status}", target=supplier, after={"status": status})

@transaction.atomic
def set_account_status(*, user, actor, status):
    before = {"account_status": user.account_status}
    user.account_status = status
    user.save(update_fields=["account_status", "is_active", "updated_at"])
    log_action(actor=actor, action=f"ACCOUNT_{status}", target=user, before=before, after={"account_status": status})
