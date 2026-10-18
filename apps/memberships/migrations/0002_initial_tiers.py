from django.db import migrations
def seed_tiers(apps, schema_editor):
    Tier = apps.get_model("memberships", "MembershipTier")
    Tier.objects.get_or_create(code="STANDARD", defaults={"name": "Standard"})
    Tier.objects.get_or_create(code="SPECIAL", defaults={"name": "Special"})
class Migration(migrations.Migration):
    dependencies = [("memberships", "0001_initial")]
    operations = [migrations.RunPython(seed_tiers, migrations.RunPython.noop)]
