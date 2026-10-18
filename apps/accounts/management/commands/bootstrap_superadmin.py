from django.core.management.base import BaseCommand, CommandError
import os
from apps.accounts.models import User
class Command(BaseCommand):
    help = "Create the first BUILTASUPPLY superadmin. Use only during controlled deployment."
    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--password", help="Avoid in shared shell history; prefer BUILTASUPPLY_BOOTSTRAP_PASSWORD.")
    def handle(self, *args, **options):
        if User.objects.filter(primary_role="SUPERADMIN").exists(): raise CommandError("A superadmin already exists.")
        password = options["password"] or os.environ.get("BUILTASUPPLY_BOOTSTRAP_PASSWORD")
        if not password: raise CommandError("Supply a password through BUILTASUPPLY_BOOTSTRAP_PASSWORD or --password.")
        user = User.objects.create_superuser(options["email"], password)
        self.stdout.write(self.style.SUCCESS(f"Created superadmin {user.email}"))
