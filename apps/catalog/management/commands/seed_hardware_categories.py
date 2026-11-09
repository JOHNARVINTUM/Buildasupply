from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.models import Category


class Command(BaseCommand):
    help = "Add general hardware categories without changing existing categories."

    @transaction.atomic
    def handle(self, *args, **options):
        categories = (
            ("Hand Tools", "hand-tools", "Hammers, screwdrivers, pliers, wrenches, and measuring tools."),
            ("Power Tools & Accessories", "power-tools-accessories", "Drills, saws, grinders, bits, blades, and attachments."),
            ("Fasteners & Fixings", "fasteners-fixings", "Nails, screws, bolts, nuts, anchors, and brackets."),
            ("Building Materials", "building-materials", "Cement, sand, aggregates, blocks, timber, and steel."),
            ("Plumbing Supplies", "plumbing-supplies", "Pipes, fittings, valves, faucets, and drainage supplies."),
            ("Electrical Supplies", "electrical-supplies", "Wires, switches, outlets, breakers, and lighting supplies."),
            ("Paint & Finishing", "paint-finishing", "Paint, primer, coatings, brushes, rollers, and abrasives."),
            ("Adhesives & Sealants", "adhesives-sealants", "Glues, tapes, silicone, sealants, and fillers."),
            ("Door & Window Hardware", "door-window-hardware", "Hinges, handles, locks, latches, and window fittings."),
            ("Safety & Workwear", "safety-workwear", "Gloves, helmets, eye protection, masks, and workwear."),
            ("Garden & Outdoor", "garden-outdoor", "Garden tools, hoses, irrigation, and outdoor maintenance supplies."),
            ("General Hardware", "general-hardware", "Other hardware and maintenance supplies."),
        )
        created = 0
        for name, slug, description in categories:
            # Respect categories already maintained by the catalog team.
            if Category.objects.filter(name__iexact=name).exists():
                continue
            _, added = Category.objects.get_or_create(
                slug=slug,
                defaults={"name": name, "description": description},
            )
            created += int(added)
        self.stdout.write(self.style.SUCCESS(f"Added {created} hardware categories."))
