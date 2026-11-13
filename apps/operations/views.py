import logging
from django.contrib.auth.decorators import user_passes_test
from django.db.models import Q, Sum
from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from apps.audit.models import AuditLog
from apps.catalog.models import Product
from apps.payments.models import CODCollection, CODException, CODReceiptConfirmation, Payment, PaymentReconciliation, RefundWalletReversal
from apps.payouts.models import PayoutRequest
from apps.suppliers.models import Supplier
from apps.catalog.services import moderate_product, transition_supplier
from apps.wallets.models import Wallet
from apps.wallets.models import SettlementRecord
from apps.wallets.services import release_settlement
from apps.inventory.models import InventoryMovement, InventoryReservation
from apps.orders.models import MasterOrder, SupplierOrder
from apps.accounts.models import User
from apps.accounts.forms import StaffBuyerCreateForm
from apps.accounts.services import register_staff_buyer, set_account_status
logger = logging.getLogger(__name__)
def admin_required(view):return user_passes_test(lambda u:u.is_authenticated and u.primary_role=="SUPERADMIN" and u.account_status=="ACTIVE")(view)
@admin_required
def dashboard(request):
    wallet=Wallet.objects.aggregate(pending=Sum("pending_cached"),available=Sum("available_cached"))
    cod_orders=SupplierOrder.objects.filter(master_order__cod_commitment__isnull=False)
    exceptions=CODException.objects.filter(status__in=["FAILED_DELIVERY","DISPUTED"])
    return render(request,"operations/dashboard.html",{"pending_suppliers":Supplier.objects.filter(approval_status="PENDING_REVIEW").count(),"pending_products":Product.objects.filter(status="PENDING_REVIEW").count(),"failed_payments":Payment.objects.filter(status="FAILED").count(),"pending_payouts":PayoutRequest.objects.filter(status="REQUESTED").count(),"wallet":wallet,"actions":AuditLog.objects.order_by("-created_at")[:12],"cod_metrics":{"total":cod_orders.count(),"incoming":cod_orders.filter(status="PENDING_SUPPLIER").count(),"accepted":cod_orders.filter(status="CONFIRMED").count(),"preparing":cod_orders.filter(status="PREPARING").count(),"dispatched":cod_orders.filter(status="SHIPPED").count(),"delivered":cod_orders.filter(status="DELIVERED").count(),"collections":CODCollection.objects.filter(supplier_order__in=cod_orders).count(),"awaiting_receipt":cod_orders.filter(status="DELIVERED",cod_collection__isnull=False,cod_receipt_confirmation__isnull=True).count(),"exceptions":exceptions.count(),"settlements_pending":SettlementRecord.objects.filter(supplier_order__in=cod_orders,status="PENDING").count(),"settlements_held":SettlementRecord.objects.filter(supplier_order__in=cod_orders,status="HELD").count()}})
@admin_required
def audit_view(request):return render(request,"operations/audit.html",{"logs":AuditLog.objects.select_related("actor").order_by("-created_at")[:100]})

@admin_required
def users(request):
    query=request.GET.get("q", "").strip()
    accounts=User.objects.order_by("email")
    if query: accounts=accounts.filter(email__icontains=query)
    page=Paginator(accounts, 25).get_page(request.GET.get("page"))
    return render(request, "operations/users.html", {"page": page, "query": query})

@admin_required
def update_user_status(request, pk):
    if request.method != "POST": return redirect("operations-users")
    account=get_object_or_404(User, pk=pk)
    status=request.POST.get("status")
    allowed={choice for choice, _ in User.AccountStatus.choices}
    if account == request.user:
        messages.error(request, "You cannot change your own account status here.")
    elif status not in allowed:
        messages.error(request, "Invalid account status.")
    else:
        set_account_status(user=account, actor=request.user, status=status)
        messages.success(request, f"Updated {account.email} to {status.replace('_', ' ').title()}.")
    return redirect("operations-users")


@admin_required
def staff_buyers(request):
    """Create and manage local BUILTASUPPLY purchasing accounts for staff."""
    if request.method == "POST":
        form = StaffBuyerCreateForm(request.POST)
        if form.is_valid():
            buyer = register_staff_buyer(
                actor=request.user,
                email=form.cleaned_data["email"],
                password1=form.cleaned_data["password1"],
                full_name=form.cleaned_data["full_name"],
                phone=form.cleaned_data["phone"],
            )
            messages.success(request, f"Created staff buyer account for {buyer.full_name or buyer.email}.")
            return redirect("operations-staff-buyers")
    else:
        form = StaffBuyerCreateForm()

    query = request.GET.get("q", "").strip()
    buyers = User.objects.filter(primary_role=User.GlobalRole.STAFF_BUYER).order_by("email")
    if query:
        buyers = buyers.filter(Q(email__icontains=query) | Q(full_name__icontains=query))
    page = Paginator(buyers, 25).get_page(request.GET.get("page"))
    return render(request, "operations/staff_buyers.html", {"form": form, "page": page, "query": query})


@admin_required
def staff_purchases(request):
    """Read-only operational monitoring of orders created by staff buyers."""
    orders = (
        MasterOrder.objects.filter(customer__user__primary_role=User.GlobalRole.STAFF_BUYER)
        .select_related("customer__user")
        .prefetch_related("supplier_orders__delivery")
        .order_by("-placed_at")
    )
    if value := request.GET.get("staff"):
        orders = orders.filter(customer__user_id=value)
    if value := request.GET.get("order"):
        orders = orders.filter(Q(order_number__icontains=value) | Q(customer__user__email__icontains=value))
    if value := request.GET.get("payment_status"):
        orders = orders.filter(payment_status=value)
    if value := request.GET.get("status"):
        orders = orders.filter(status=value)
    if value := request.GET.get("delivery_status"):
        orders = orders.filter(supplier_orders__delivery__status=value).distinct()

    metrics = orders.aggregate(total=Sum("total_minor"))
    page = Paginator(orders, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "operations/staff_purchases.html",
        {
            "page": page,
            "staff_buyers": User.objects.filter(primary_role=User.GlobalRole.STAFF_BUYER).order_by("full_name", "email"),
            "filters": request.GET,
            "order_statuses": SupplierOrder.Status.choices,
            "payment_statuses": Payment.Status.choices,
            "staff_order_count": orders.count(),
            "staff_order_total_minor": metrics["total"] or 0,
        },
    )

@admin_required
def suppliers(request):
    query=request.GET.get("q", "").strip()
    suppliers=Supplier.objects.order_by("approval_status", "display_name")
    if query: suppliers=suppliers.filter(display_name__icontains=query)
    page=Paginator(suppliers, 25).get_page(request.GET.get("page"))
    return render(request, "operations/suppliers.html", {"page": page, "query": query})

@admin_required
def update_supplier_status(request, pk):
    if request.method != "POST": return redirect("operations-suppliers")
    supplier=get_object_or_404(Supplier, pk=pk)
    status=request.POST.get("status")
    try:
        transition_supplier(supplier=supplier, actor=request.user, status=status, reason=request.POST.get("reason", ""))
        messages.success(request, f"Updated {supplier.display_name} to {status.replace('_', ' ').title()}.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("operations-suppliers")

@admin_required
def supplier_products(request, pk):
    supplier=get_object_or_404(Supplier, pk=pk)
    products=Product.objects.filter(supplier=supplier).select_related("category", "inventory").order_by("-updated_at")
    return render(request, "operations/supplier_products.html", {"supplier":supplier, "products":products})

@admin_required
def update_product_status(request, supplier_pk, product_pk):
    if request.method != "POST": return redirect("operations-supplier-products", pk=supplier_pk)
    supplier=get_object_or_404(Supplier, pk=supplier_pk)
    product=get_object_or_404(Product, pk=product_pk, supplier=supplier)
    action=request.POST.get("action")
    try:
        moderate_product(product=product, actor=request.user, approve=action == "approve", reason=request.POST.get("reason", ""))
        messages.success(request, f"Updated {product.name}.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("operations-supplier-products", pk=supplier.pk)


def _cod_orders(request):
    orders=SupplierOrder.objects.filter(master_order__cod_commitment__isnull=False).select_related("master_order__customer__user","supplier","delivery").prefetch_related("items","cod_exceptions").order_by("-master_order__placed_at")
    if value:=request.GET.get("supplier"): orders=orders.filter(supplier_id=value)
    if value:=request.GET.get("customer"): orders=orders.filter(master_order__customer__user__email__icontains=value)
    if value:=request.GET.get("order"): orders=orders.filter(Q(id__icontains=value)|Q(master_order__order_number__icontains=value))
    if value:=request.GET.get("status"): orders=orders.filter(status=value)
    if value:=request.GET.get("delivery_status"): orders=orders.filter(delivery__status=value)
    if request.GET.get("collection") == "recorded": orders=orders.filter(cod_collection__isnull=False)
    if request.GET.get("collection") == "awaiting": orders=orders.filter(cod_collection__isnull=True)
    if request.GET.get("receipt") == "confirmed": orders=orders.filter(cod_receipt_confirmation__isnull=False)
    if request.GET.get("receipt") == "awaiting": orders=orders.filter(cod_receipt_confirmation__isnull=True)
    if request.GET.get("exception") == "open": orders=orders.filter(cod_exceptions__status__in=["FAILED_DELIVERY","DISPUTED"]).distinct()
    if value:=request.GET.get("from"): orders=orders.filter(master_order__placed_at__date__gte=value)
    if value:=request.GET.get("to"): orders=orders.filter(master_order__placed_at__date__lte=value)
    return orders


@admin_required
def cod_orders(request):
    page=Paginator(_cod_orders(request),25).get_page(request.GET.get("page"))
    return render(request,"operations/cod_orders.html",{"page":page,"suppliers":Supplier.objects.order_by("display_name"),"filters":request.GET})


@admin_required
def cod_order_detail(request, pk):
    supplier_order=get_object_or_404(SupplierOrder.objects.filter(master_order__cod_commitment__isnull=False).select_related("master_order__customer__user","supplier","delivery","settlement__wallet").prefetch_related("items","inventory_reservations__inventory__product","cod_exceptions__reported_by","master_order__payment_reconciliations__history","master_order__financial_lines"),pk=pk)
    timeline=AuditLog.objects.filter(Q(target_type="orders.SupplierOrder",target_id=supplier_order.pk)|Q(target_type="payments.CODCollection",target_id=getattr(getattr(supplier_order,"cod_collection",None),"pk",None))|Q(target_type="payments.CODException",target_id__in=supplier_order.cod_exceptions.values_list("pk",flat=True))).select_related("actor").order_by("created_at")
    movements=InventoryMovement.objects.filter(reference_type="orders.SupplierOrder",reference_id=supplier_order.pk).select_related("inventory__product","actor").order_by("created_at")
    return render(request,"operations/cod_order_detail.html",{"supplier_order":supplier_order,"timeline":timeline,"movements":movements})


@admin_required
def failed_deliveries(request):
    cases=CODException.objects.filter(status__in=["FAILED_DELIVERY","RETURN_VERIFIED"]).select_related("supplier_order__master_order","supplier_order__supplier","reported_by","supplier_order__delivery").prefetch_related("supplier_order__inventory_reservations__inventory","supplier_order__cod_exceptions").order_by("-created_at")
    return render(request,"operations/cod_failed_deliveries.html",{"page":Paginator(cases,25).get_page(request.GET.get("page"))})


@admin_required
def verify_return(request, pk):
    if request.method!="POST": return redirect("operations-failed-deliveries")
    exception=get_object_or_404(CODException,pk=pk,status="FAILED_DELIVERY")
    reason=request.POST.get("reason","").strip()
    if not reason:
        messages.error(request,"A return verification explanation or reference is required.")
        return redirect("operations-cod-order-detail",pk=exception.supplier_order_id)
    try:
        from apps.payments.services import verify_cod_return
        verify_cod_return(exception=exception,actor=request.user)
        from apps.audit.services import log_action
        log_action(actor=request.user,action="COD_RETURN_VERIFICATION_NOTES",target=exception,after={"reason":reason,"supplier_order_id":str(exception.supplier_order_id)})
        messages.success(request,"Return verified. Only this supplier order's active reservations were released.")
    except Exception:
        logger.exception("COD return verification failed")
        messages.error(request,"Return verification could not be completed.")
    return redirect("operations-cod-order-detail",pk=exception.supplier_order_id)


@admin_required
def collection_disputes(request):
    cases=CODException.objects.filter(status="DISPUTED").select_related("supplier_order__master_order","supplier_order__supplier","reported_by","supplier_order__delivery").prefetch_related("supplier_order__cod_exceptions").order_by("-created_at")
    return render(request,"operations/cod_disputes.html",{"page":Paginator(cases,25).get_page(request.GET.get("page"))})


@admin_required
def settlements(request):
    rows=SettlementRecord.objects.filter(supplier_order__master_order__cod_commitment__isnull=False).select_related("supplier_order__supplier","supplier_order__master_order","wallet").prefetch_related("supplier_order__cod_exceptions").order_by("status","supplier_order__master_order__placed_at")
    if status:=request.GET.get("status"):rows=rows.filter(status=status)
    return render(request,"operations/cod_settlements.html",{"page":Paginator(rows,25).get_page(request.GET.get("page"))})


@admin_required
def release_cod_settlement(request, pk):
    if request.method!="POST": return redirect("operations-cod-settlements")
    settlement=get_object_or_404(SettlementRecord.objects.filter(supplier_order__master_order__cod_commitment__isnull=False),pk=pk)
    try:
        release_settlement(settlement,actor=request.user)
        from apps.audit.services import log_action
        log_action(actor=request.user,action="COD_SETTLEMENT_RELEASE_REQUESTED",target=settlement,after={"status":"RELEASED"})
        messages.success(request,"Settlement released through the validated settlement service.")
    except Exception as error:
        messages.error(request,str(error))
    return redirect("operations-cod-settlements")


@admin_required
def held_reversals(request):
    rows=RefundWalletReversal.objects.filter(status="HELD").select_related("refund_allocation__refund","refund_allocation__supplier_order__supplier","wallet").order_by("-created_at")
    return render(request,"operations/held_reversals.html",{"page":Paginator(rows,25).get_page(request.GET.get("page"))})


@admin_required
def reconciliations(request):
    rows=PaymentReconciliation.objects.select_related("payment","master_order","resolved_by").prefetch_related("history__actor").order_by("status","-created_at")
    return render(request,"operations/reconciliations.html",{"page":Paginator(rows,25).get_page(request.GET.get("page"))})


@admin_required
def resolve_reconciliation(request, pk):
    if request.method!="POST": return redirect("operations-reconciliations")
    reconciliation=get_object_or_404(PaymentReconciliation,pk=pk)
    resolution=request.POST.get("resolution","");notes=request.POST.get("notes","").strip()
    if resolution not in {"INVESTIGATING","REFUND_REQUIRED","REALLOCATE"} or not notes:
        messages.error(request,"Select an approved resolution and provide investigation notes.")
        return redirect("operations-reconciliations")
    try:
        from apps.payments.services import resolve_payment_reconciliation
        resolve_payment_reconciliation(reconciliation=reconciliation,actor=request.user,resolution=resolution,notes=notes)
        messages.success(request,"Reconciliation updated through the validated resolution service.")
    except Exception as error:
        messages.error(request,str(error))
    return redirect("operations-reconciliations")
