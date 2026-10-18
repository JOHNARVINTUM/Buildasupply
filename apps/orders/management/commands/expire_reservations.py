from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from apps.inventory.models import InventoryReservation
from apps.payments.services import release_reservations


class Command(BaseCommand):
    help = "Expires abandoned checkout reservations, restores stock, and cancels unpaid orders."

    def handle(self, *args, **options):
        order_ids = set(InventoryReservation.objects.filter(status="ACTIVE", expires_at__lte=timezone.now()).values_list("supplier_order__master_order_id", flat=True))
        for order_id in order_ids:
            with transaction.atomic():
                from apps.orders.models import MasterOrder
                order = MasterOrder.objects.select_for_update().get(pk=order_id)
                if order.status != "PENDING_PAYMENT": continue
                release_reservations(master_order=order, expired=True)
                order.status="CANCELLED";order.payment_status="EXPIRED";order.save(update_fields=["status","payment_status"])
                order.supplier_orders.exclude(status="CANCELLED").update(status="CANCELLED")
        self.stdout.write(self.style.SUCCESS(f"Expired {len(order_ids)} unpaid order reservation set(s)."))
