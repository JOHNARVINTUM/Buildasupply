import json
import logging
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import log_action
from apps.inventory.models import InventoryReservation
from apps.orders.models import MasterOrder
from apps.payments.models import Payment, PaymentReconciliation
from apps.payments.services import release_reservations


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Expires abandoned unpaid checkout reservations, restores stock, and cancels their orders."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report qualifying reservations without changing records.")

    def _emit(self, event, level=logging.INFO, **fields):
        """Keep operational data structured without including payment/customer secrets."""
        logger.log(level, event, extra={"reservation_expiry": {"event": event, **fields}})

    def handle(self, *args, **options):
        started = time.monotonic()
        dry_run = options["dry_run"]
        now = timezone.now()
        candidate_reservations = InventoryReservation.objects.filter(status="ACTIVE", expires_at__lte=now)
        candidate_order_ids = list(candidate_reservations.order_by("supplier_order__master_order_id").values_list("supplier_order__master_order_id", flat=True).distinct())
        metrics = {
            "dry_run": dry_run,
            "expired_reservations_discovered": candidate_reservations.count(),
            "candidate_orders": len(candidate_order_ids),
            "orders_processed": 0,
            "reservations_released": 0,
            "orders_skipped": 0,
            "reconciliation_cases": 0,
            "errors": 0,
        }

        for order_id in candidate_order_ids:
            try:
                if dry_run:
                    self._dry_run_order(order_id=order_id, now=now, metrics=metrics)
                else:
                    self._expire_order(order_id=order_id, now=now, metrics=metrics)
            except Exception:
                metrics["errors"] += 1
                self._emit("reservation_expiry_order_failed", logging.ERROR, order_id=str(order_id))
                logger.exception("Reservation expiry failed for order %s", order_id)

        metrics["duration_ms"] = round((time.monotonic() - started) * 1000)
        self._emit("reservation_expiry_completed", logging.ERROR if metrics["errors"] else logging.INFO, **metrics)
        self.stdout.write(json.dumps(metrics, sort_keys=True))
        if metrics["errors"]:
            raise CommandError(f"Reservation expiry completed with {metrics['errors']} recoverable order error(s).")

    def _eligible_locked_reservations(self, order, now):
        return InventoryReservation.objects.filter(
            supplier_order__master_order=order,
            status="ACTIVE",
            expires_at__lte=now,
        )

    def _skip_reason(self, order):
        if order.payment_status == "COD_PENDING" and order.status == "COD_COMMITTED":
            return "ACTIVE_COD_COMMITMENT"
        if order.payment_status == "PAID" or order.status not in {"PENDING_PAYMENT"}:
            return "ORDER_NOT_UNPAID"
        if PaymentReconciliation.objects.filter(
            master_order=order,
            status__in=[PaymentReconciliation.Status.OPEN, PaymentReconciliation.Status.INVESTIGATING],
        ).exists():
            return "ACTIVE_RECONCILIATION"
        return None

    def _dry_run_order(self, *, order_id, now, metrics):
        order = MasterOrder.objects.filter(pk=order_id).first()
        if not order:
            metrics["orders_skipped"] += 1
            return
        reservations = self._eligible_locked_reservations(order, now)
        count = reservations.count()
        if not count:
            metrics["orders_skipped"] += 1
            return
        reason = self._skip_reason(order)
        if reason:
            metrics["orders_skipped"] += 1
            if reason == "ACTIVE_RECONCILIATION":
                metrics["reconciliation_cases"] += 1
            self._emit("reservation_expiry_skipped", order_id=str(order.id), reason=reason, dry_run=True)
            return
        metrics["orders_processed"] += 1
        metrics["reservations_released"] += count
        self._emit("reservation_expiry_would_process", order_id=str(order.id), reservation_count=count)

    def _expire_order(self, *, order_id, now, metrics):
        # Lock hierarchy: MasterOrder -> Payment -> SupplierOrder -> InventoryReservation -> Inventory.
        # Payment confirmation begins with MasterOrder too, so the winner determines whether
        # normal fulfillment or late-payment reconciliation is appropriate.
        with transaction.atomic():
            order = MasterOrder.objects.select_for_update().get(pk=order_id)
            list(Payment.objects.select_for_update().filter(master_order=order).order_by("pk"))
            reservations = self._eligible_locked_reservations(order, now)
            reservation_count = reservations.count()
            if not reservation_count:
                metrics["orders_skipped"] += 1
                return
            reason = self._skip_reason(order)
            if reason:
                metrics["orders_skipped"] += 1
                if reason == "ACTIVE_RECONCILIATION":
                    metrics["reconciliation_cases"] += 1
                self._emit("reservation_expiry_skipped", order_id=str(order.id), reason=reason, dry_run=False)
                return
            release_reservations(master_order=order, expired=True)
            order.status = "CANCELLED"
            order.payment_status = "EXPIRED"
            order.save(update_fields=["status", "payment_status"])
            order.supplier_orders.exclude(status="CANCELLED").update(status="CANCELLED")
            log_action(actor=None, action="ORDER_RESERVATIONS_EXPIRED", target=order, after={"reservations_released": reservation_count, "payment_status": order.payment_status, "status": order.status})
            metrics["orders_processed"] += 1
            metrics["reservations_released"] += reservation_count
            self._emit("reservation_expiry_processed", order_id=str(order.id), reservation_count=reservation_count)
