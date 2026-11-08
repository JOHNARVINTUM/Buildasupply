# Generated manually for the existing CustomerAddress default-address invariant.
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("customers", "0002_customeraddress")]

    operations = [
        migrations.AddConstraint(
            model_name="customeraddress",
            constraint=models.UniqueConstraint(
                fields=("customer",),
                condition=Q(("is_default", True)),
                name="one_default_address_per_customer",
            ),
        ),
    ]
