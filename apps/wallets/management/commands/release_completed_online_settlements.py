from django.core.management.base import BaseCommand

from apps.wallets.models import SettlementRecord
from apps.wallets.services import release_settlement


class Command(BaseCommand):
    help = "Release completed online-paid settlements that predate automatic wallet release."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="List eligible settlements without changing wallets.")

    def handle(self, *args, **options):
        settlements = SettlementRecord.objects.filter(
            status__in=[SettlementRecord.Status.PENDING, SettlementRecord.Status.ELIGIBLE],
            supplier_order__status="COMPLETED",
            supplier_order__master_order__payment_status="PAID",
            supplier_order__master_order__cod_commitment__isnull=True,
        ).select_related("supplier_order__master_order", "wallet").order_by("pk")
        eligible = settlements.count()
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING(f"{eligible} completed online settlement(s) are eligible for release."))
            return
        released = 0
        for settlement in settlements.iterator():
            release_settlement(settlement)
            released += 1
        self.stdout.write(self.style.SUCCESS(f"Released {released} completed online settlement(s)."))
