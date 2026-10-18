from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from apps.audit.services import log_action
from .models import SettlementRecord, Wallet, WalletLedgerEntry
def get_wallet(supplier,currency="PHP"):return Wallet.objects.get_or_create(supplier=supplier,currency=currency)[0]
def balances(wallet):
    q=wallet.entries.filter(status__in=["POSTED","RESERVED"])
    return {"pending":q.filter(bucket="PENDING").aggregate(x=Sum("amount_minor"))["x"] or 0,"available":q.filter(bucket="AVAILABLE").aggregate(x=Sum("amount_minor"))["x"] or 0,"lifetime_earned":q.filter(entry_type="SALE").aggregate(x=Sum("amount_minor"))["x"] or 0,"lifetime_paid_out":-(q.filter(entry_type="PAYOUT",status="POSTED").aggregate(x=Sum("amount_minor"))["x"] or 0)}
def refresh_cached(wallet):
    data=balances(wallet);Wallet.objects.filter(pk=wallet.pk).update(pending_cached=data["pending"],available_cached=data["available"],lifetime_earned_cached=data["lifetime_earned"],lifetime_paid_out_cached=data["lifetime_paid_out"]);return data
@transaction.atomic
def post_payment_earnings(master_order):
    for so in master_order.supplier_orders.select_related("supplier").all():
        wallet=get_wallet(so.supplier,so.currency);gross=so.total_minor;fee=so.platform_fee_minor;net=gross-fee
        settlement,created=SettlementRecord.objects.get_or_create(supplier_order=so,defaults={"wallet":wallet,"gross_minor":gross,"platform_fee_minor":fee,"net_pending_minor":net,"currency":so.currency,"policy_snapshot":{"rule":"RELEASE_AFTER_COMPLETION","version":"v1"}})
        if not created:continue
        WalletLedgerEntry.objects.create(wallet=wallet,entry_type="SALE",bucket="PENDING",amount_minor=gross,currency=so.currency,reference=f"sale:{so.id}",source_type="orders.SupplierOrder",source_id=so.id)
        if fee:WalletLedgerEntry.objects.create(wallet=wallet,entry_type="PLATFORM_FEE",bucket="PENDING",amount_minor=-fee,currency=so.currency,reference=f"fee:{so.id}",source_type="orders.SupplierOrder",source_id=so.id)
        refresh_cached(wallet)
@transaction.atomic
def release_settlement(settlement,actor=None):
    settlement=SettlementRecord.objects.select_for_update().select_related("wallet","supplier_order").get(pk=settlement.pk)
    if settlement.status=="RELEASED":return settlement
    if settlement.supplier_order.status!="COMPLETED":raise ValidationError("Settlement is not eligible before completion.")
    wallet=Wallet.objects.select_for_update().get(pk=settlement.wallet_id);amount=settlement.net_pending_minor
    WalletLedgerEntry.objects.create(wallet=wallet,entry_type="SETTLEMENT",bucket="PENDING",amount_minor=-amount,currency=wallet.currency,reference=f"settlement-pending:{settlement.id}",source_type="wallets.SettlementRecord",source_id=settlement.id)
    WalletLedgerEntry.objects.create(wallet=wallet,entry_type="SETTLEMENT",bucket="AVAILABLE",amount_minor=amount,currency=wallet.currency,reference=f"settlement-available:{settlement.id}",source_type="wallets.SettlementRecord",source_id=settlement.id)
    settlement.status="RELEASED";settlement.released_at=timezone.now();settlement.save(update_fields=["status","released_at"]);refresh_cached(wallet);return settlement
@transaction.atomic
def reverse_refund(refund,actor=None):
    for allocation in refund.allocations.select_related("supplier_order","supplier_order__settlement").all():
        settlement=allocation.supplier_order.settlement;wallet=Wallet.objects.select_for_update().get(pk=settlement.wallet_id);bucket="AVAILABLE" if settlement.status=="RELEASED" else "PENDING";ref=f"refund:{refund.id}:{allocation.id}"
        if WalletLedgerEntry.objects.filter(reference=ref).exists():continue
        WalletLedgerEntry.objects.create(wallet=wallet,entry_type="REFUND",bucket=bucket,amount_minor=-allocation.amount_minor,currency=wallet.currency,reference=ref,source_type="payments.Refund",source_id=refund.id);refresh_cached(wallet)
@transaction.atomic
def adjust_wallet(wallet,actor,amount_minor,reason,reference):
    if actor.primary_role!="SUPERADMIN" or not reason or not reference:raise ValidationError("Superadmin, reason, and reference required.")
    wallet=Wallet.objects.select_for_update().get(pk=wallet.pk);WalletLedgerEntry.objects.create(wallet=wallet,entry_type="ADJUSTMENT",bucket="AVAILABLE",amount_minor=amount_minor,currency=wallet.currency,reference=f"adjust:{reference}",source_type="manual",reason=reason);refresh_cached(wallet);log_action(actor=actor,action="WALLET_ADJUSTMENT",target=wallet,after={"amount_minor":amount_minor})
def reconcile(wallet):
    expected=balances(wallet);return {"wallet_id":wallet.id,"expected":expected,"cached":{"pending":wallet.pending_cached,"available":wallet.available_cached},"difference":{"pending":expected["pending"]-wallet.pending_cached,"available":expected["available"]-wallet.available_cached}}
