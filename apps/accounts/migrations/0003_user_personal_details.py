from django.db import migrations, models


def populate_personal_details(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    CustomerProfile = apps.get_model("customers", "CustomerProfile")
    Membership = apps.get_model("suppliers", "SupplierStaffMembership")
    alias = schema_editor.connection.alias
    for profile in CustomerProfile.objects.using(alias).all().iterator():
        User.objects.using(alias).filter(pk=profile.user_id).update(full_name=profile.full_name, phone=profile.phone)
    for membership in Membership.objects.using(alias).filter(role="OWNER", status="ACTIVE").select_related("supplier").iterator():
        User.objects.using(alias).filter(pk=membership.user_id, full_name="").update(full_name=membership.supplier.contact_name)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_termsacceptance"), ("customers", "0003_one_default_address_per_customer"), ("suppliers", "0003_registration_details")]
    operations = [
        migrations.AddField(model_name="user", name="full_name", field=models.CharField(blank=True, max_length=160)),
        migrations.AddField(model_name="user", name="phone", field=models.CharField(blank=True, max_length=32)),
        migrations.RunPython(populate_personal_details, migrations.RunPython.noop),
    ]
