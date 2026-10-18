import hashlib
from django.core.exceptions import ValidationError
from django.db import transaction
from apps.audit.services import log_action
from apps.wallets.models import Wallet,WalletLedgerEntry
from apps.wallets.services import balances,refresh_cached
from .models import PayoutRequest,PayoutTransaction
@transaction.atomic
def request_payout(wallet,method,amount_minor,requester,idempotency_key):
    wallet=Wallet.objects.select_for_update().get(pk=wallet.pk);old=PayoutRequest.objects.filter(wallet=wallet,idempotency_key=idempotency_key).first()
    if old:return old
    if not method.is_active or method.wallet_id!=wallet.id or amount_minor<=0 or amount_minor>balances(wallet)["available"]:raise ValidationError("Payout amount or method invalid.")
    return PayoutRequest.objects.create(wallet=wallet,method=method,amount_minor=amount_minor,currency=wallet.currency,requester=requester,idempotency_key=idempotency_key)
@transaction.atomic
def approve_payout(payout,actor):
    if actor.primary_role!="SUPERADMIN":raise ValidationError("Superadmin required.")
    payout=PayoutRequest.objects.select_for_update().select_related("wallet").get(pk=payout.pk)
    if payout.status!="REQUESTED":raise ValidationError("Invalid payout transition.")
    wallet=Wallet.objects.select_for_update().get(pk=payout.wallet_id)
    if payout.amount_minor>balances(wallet)["available"]:raise ValidationError("Insufficient available funds.")
    WalletLedgerEntry.objects.create(wallet=wallet,entry_type="PAYOUT",bucket="AVAILABLE",amount_minor=-payout.amount_minor,currency=wallet.currency,reference=f"payout-reserve:{payout.id}",source_type="payouts.PayoutRequest",source_id=payout.id,status="RESERVED");payout.status="APPROVED";payout.reviewer=actor;payout.save(update_fields=["status","reviewer","updated_at"]);refresh_cached(wallet);log_action(actor=actor,action="PAYOUT_APPROVED",target=payout)
@transaction.atomic
def complete_payout(payout,actor=None,failed=False):
    payout=PayoutRequest.objects.select_for_update().select_related("wallet").get(pk=payout.pk);wallet=Wallet.objects.select_for_update().get(pk=payout.wallet_id)
    if payout.status not in {"APPROVED","PROCESSING"}:return payout
    reserve=wallet.entries.get(reference=f"payout-reserve:{payout.id}")
    if failed:
        WalletLedgerEntry.objects.create(wallet=wallet,entry_type="REVERSAL",bucket="AVAILABLE",amount_minor=payout.amount_minor,currency=wallet.currency,reference=f"payout-fail:{payout.id}",source_type="payouts.PayoutRequest",source_id=payout.id);payout.status="FAILED"
    else:reserve.status="POSTED";reserve.save(update_fields=["status"]);payout.status="COMPLETED"
    payout.save(update_fields=["status","updated_at"]);refresh_cached(wallet);return payout
