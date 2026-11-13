from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from apps.audit.services import log_action
from .models import SettlementRecord, Wallet, WalletLedgerEntry
def get_wallet(supplier,currency="PHP"):return Wallet.objects.get_or_create(supplier=supplier,currency=currency)[0]
def balances(wallet):
    q=wallet.entries.filter(status__in=["POSTED","RESERVED"])
    earned=q.filter(status="POSTED",entry_type__in=["SALE","REFUND"]).aggregate(x=Sum("amount_minor"))["x"] or 0
    return {"pending":q.filter(bucket="PENDING").aggregate(x=Sum("amount_minor"))["x"] or 0,"available":q.filter(bucket="AVAILABLE").aggregate(x=Sum("amount_minor"))["x"] or 0,"lifetime_earned":earned,"lifetime_paid_out":-(q.filter(entry_type="PAYOUT",status="POSTED").aggregate(x=Sum("amount_minor"))["x"] or 0)}
def refresh_cached(wallet):
    data=balances(wallet);Wallet.objects.filter(pk=wallet.pk).update(pending_cached=data["pending"],available_cached=data["available"],lifetime_earned_cached=data["lifetime_earned"],lifetime_paid_out_cached=data["lifetime_paid_out"]);return data
@transaction.atomic
def post_payment_earnings(master_order):
    for so in master_order.supplier_orders.select_related("supplier").all():
        post_supplier_order_earnings(so,accepted=False)
@transaction.atomic
def post_supplier_order_earnings(so,accepted=True):
    so=SettlementRecord._meta.get_field("supplier_order").remote_field.model.objects.select_related("supplier").get(pk=so.pk)
    wallet=get_wallet(so.supplier,so.currency);gross=so.total_minor;fee=so.platform_fee_minor;net=gross-fee
    settlement,created=SettlementRecord.objects.get_or_create(supplier_order=so,defaults={"wallet":wallet,"gross_minor":gross,"platform_fee_minor":fee,"net_pending_minor":net,"currency":so.currency,"policy_snapshot":{"rule":"EARN_AFTER_SUPPLIER_ACCEPTANCE_RELEASE_AFTER_COMPLETION","version":"v2"}})
    if not created:return settlement
    ledger_status="POSTED" if accepted else "RESERVED"
    WalletLedgerEntry.objects.create(wallet=wallet,entry_type="SALE",bucket="PENDING",amount_minor=gross,currency=so.currency,reference=f"sale:{so.id}",source_type="orders.SupplierOrder",source_id=so.id,status=ledger_status)
    if fee:WalletLedgerEntry.objects.create(wallet=wallet,entry_type="PLATFORM_FEE",bucket="PENDING",amount_minor=-fee,currency=so.currency,reference=f"fee:{so.id}",source_type="orders.SupplierOrder",source_id=so.id,status=ledger_status)
    refresh_cached(wallet);return settlement
@transaction.atomic
def accept_online_payment_earnings(supplier_order,actor=None):
    """Count a paid online sale as earned exactly once after supplier acceptance."""
    from apps.payments.models import RefundWalletReversal
    settlement=SettlementRecord.objects.select_for_update().select_related("wallet","supplier_order__master_order").get(supplier_order=supplier_order)
    if settlement.supplier_order.master_order.payment_status!="PAID" or settlement.supplier_order.status!="CONFIRMED":
        raise ValidationError("Online-paid earnings require an accepted, paid order.")
    wallet=Wallet.objects.select_for_update().get(pk=settlement.wallet_id)
    updated=WalletLedgerEntry.objects.filter(wallet=wallet,source_type="orders.SupplierOrder",source_id=settlement.supplier_order_id,entry_type__in=["SALE","PLATFORM_FEE"],status="RESERVED").update(status="POSTED")
    refund_references=RefundWalletReversal.objects.filter(wallet=wallet,status="APPLIED",refund_allocation__supplier_order_id=settlement.supplier_order_id).exclude(ledger_reference="").values_list("ledger_reference",flat=True)
    updated+=WalletLedgerEntry.objects.filter(wallet=wallet,reference__in=refund_references,status="RESERVED").update(status="POSTED")
    if updated:
        refresh_cached(wallet)
        log_action(actor=actor,action="ONLINE_PAYMENT_EARNINGS_ACCEPTED",target=settlement.supplier_order,after={"wallet_id":wallet.id,"amount_minor":settlement.gross_minor})
    return settlement
@transaction.atomic
def release_settlement(settlement,actor=None):
    settlement=SettlementRecord.objects.select_for_update().select_related("wallet","supplier_order").get(pk=settlement.pk)
    if settlement.status=="RELEASED":return settlement
    if settlement.supplier_order.status!="COMPLETED":raise ValidationError("Settlement is not eligible before completion.")
    try:
        commitment=settlement.supplier_order.master_order.cod_commitment
    except Exception:
        commitment=None
    if commitment and commitment.status=="ACTIVE":
        supplier_order=settlement.supplier_order
        if not hasattr(supplier_order,"cod_collection") or not hasattr(supplier_order,"cod_receipt_confirmation"):
            raise ValidationError("COD settlement requires verified collection and customer receipt confirmation.")
        if supplier_order.cod_exceptions.filter(status__in=["FAILED_DELIVERY","DISPUTED"]).exists():
            raise ValidationError("COD settlement is held while a delivery exception is unresolved.")
    wallet=Wallet.objects.select_for_update().get(pk=settlement.wallet_id);amount=settlement.net_pending_minor
    WalletLedgerEntry.objects.create(wallet=wallet,entry_type="SETTLEMENT",bucket="PENDING",amount_minor=-amount,currency=wallet.currency,reference=f"settlement-pending:{settlement.id}",source_type="wallets.SettlementRecord",source_id=settlement.id)
    WalletLedgerEntry.objects.create(wallet=wallet,entry_type="SETTLEMENT",bucket="AVAILABLE",amount_minor=amount,currency=wallet.currency,reference=f"settlement-available:{settlement.id}",source_type="wallets.SettlementRecord",source_id=settlement.id)
    settlement.status="RELEASED";settlement.released_at=timezone.now();settlement.save(update_fields=["status","released_at"]);refresh_cached(wallet)
    from apps.notifications.services import emit, supplier_recipient_ids
    emit("settlement.released",settlement,{"recipient_ids":supplier_recipient_ids(settlement.supplier_order.supplier),"order_number":settlement.supplier_order.master_order.order_number,"link":"/supplier/wallet/"})
    return settlement
@transaction.atomic
def reverse_refund(refund,actor=None):
    """Reverse only a provider-completed refund, without creating supplier debt automatically."""
    from apps.payments.models import Refund, RefundWalletReversal
    if refund.status != Refund.Status.COMPLETED: raise ValidationError("Only completed refunds may reverse supplier earnings.")
    allocations=list(refund.allocations.select_related("supplier_order").order_by("supplier_order_id","pk"))
    settlements={}
    for allocation in allocations:
        try: settlements[allocation.id]=allocation.supplier_order.settlement
        except SettlementRecord.DoesNotExist: settlements[allocation.id]=None
    wallet_ids=sorted({settlement.wallet_id for settlement in settlements.values() if settlement})
    wallets={wallet.id:wallet for wallet in Wallet.objects.select_for_update().filter(id__in=wallet_ids).order_by("pk")}
    for allocation in allocations:
        reversal,created=RefundWalletReversal.objects.select_for_update().get_or_create(refund_allocation=allocation,defaults={"amount_minor":allocation.amount_minor,"currency":refund.currency,"status":"HELD","reason":"PENDING_EVALUATION"})
        if reversal.status == RefundWalletReversal.Status.APPLIED: continue
        settlement=settlements[allocation.id]
        if not settlement:
            reversal.status="HELD";reversal.reason="SETTLEMENT_NOT_FOUND";reversal.save(update_fields=["status","reason","updated_at"]);continue
        wallet=wallets[settlement.wallet_id];bucket="AVAILABLE" if settlement.status=="RELEASED" else "PENDING";available=balances(wallet)[bucket.lower()]
        if available < allocation.amount_minor:
            reversal.wallet=wallet;reversal.bucket=bucket;reversal.status="HELD";reversal.reason="INSUFFICIENT_%s_BALANCE_DEBT_POLICY_REQUIRED" % bucket;reversal.save(update_fields=["wallet","bucket","status","reason","updated_at"])
            from apps.notifications.services import emit, supplier_recipient_ids, superadmin_recipient_ids
            payload={"order_number":allocation.supplier_order.master_order.order_number,"priority":"HIGH"}
            emit("refund.reversal_held",refund,{"recipient_ids":supplier_recipient_ids(allocation.supplier_order.supplier),"link":"/supplier/wallet/",**payload})
            emit("refund.reversal_held",refund,{"recipient_ids":superadmin_recipient_ids(),"link":"/operations/cod/held-reversals/",**payload})
            log_action(actor=actor,action="REFUND_WALLET_REVERSAL_HELD",target=refund,after={"allocation_id":allocation.id,"wallet_id":wallet.id,"amount_minor":allocation.amount_minor});continue
        reference=f"refund:{refund.id}:{allocation.id}"
        sale_status=WalletLedgerEntry.objects.filter(wallet=wallet,entry_type="SALE",source_id=allocation.supplier_order_id).values_list("status",flat=True).first()
        WalletLedgerEntry.objects.get_or_create(reference=reference,defaults={"wallet":wallet,"entry_type":"REFUND","bucket":bucket,"amount_minor":-allocation.amount_minor,"currency":wallet.currency,"source_type":"payments.Refund","source_id":refund.id,"status":"POSTED" if sale_status=="POSTED" else "RESERVED"})
        reversal.wallet=wallet;reversal.bucket=bucket;reversal.status="APPLIED";reversal.reason="";reversal.ledger_reference=reference;reversal.save(update_fields=["wallet","bucket","status","reason","ledger_reference","updated_at"])
        refresh_cached(wallet);log_action(actor=actor,action="REFUND_WALLET_REVERSED",target=refund,after={"allocation_id":allocation.id,"wallet_id":wallet.id,"amount_minor":allocation.amount_minor})
@transaction.atomic
def adjust_wallet(wallet,actor,amount_minor,reason,reference):
    if actor.primary_role!="SUPERADMIN" or not reason or not reference:raise ValidationError("Superadmin, reason, and reference required.")
    wallet=Wallet.objects.select_for_update().get(pk=wallet.pk);WalletLedgerEntry.objects.create(wallet=wallet,entry_type="ADJUSTMENT",bucket="AVAILABLE",amount_minor=amount_minor,currency=wallet.currency,reference=f"adjust:{reference}",source_type="manual",reason=reason);refresh_cached(wallet);log_action(actor=actor,action="WALLET_ADJUSTMENT",target=wallet,after={"amount_minor":amount_minor})
def reconcile(wallet):
    expected=balances(wallet);return {"wallet_id":wallet.id,"expected":expected,"cached":{"pending":wallet.pending_cached,"available":wallet.available_cached},"difference":{"pending":expected["pending"]-wallet.pending_cached,"available":expected["available"]-wallet.available_cached}}
