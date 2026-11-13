from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("payments", "0005_cod_backend")]

    operations = [
        migrations.AddField(model_name="payment", name="provider_merchant_reference", field=models.CharField(blank=True, max_length=160)),
        migrations.AddField(model_name="payment", name="provider_status", field=models.CharField(blank=True, max_length=32)),
        migrations.AlterField(model_name="payment", name="status", field=models.CharField(choices=[("PENDING", "Pending"), ("AUTHORIZED", "Authorized"), ("PAID", "Paid"), ("FAILED", "Failed"), ("CANCELLED", "Cancelled"), ("EXPIRED", "Expired"), ("PARTIALLY_REFUNDED", "Partially refunded"), ("REFUNDED", "Refunded")], default="PENDING", max_length=24)),
        migrations.AddConstraint(model_name="payment", constraint=models.UniqueConstraint(condition=~models.Q(("provider_merchant_reference", "")), fields=("provider_code", "provider_merchant_reference"), name="unique_provider_merchant_reference")),
    ]
