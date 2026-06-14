from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("subscriptions", "0003_webhook_secret_and_delivery_status")]

    operations = [
        migrations.AddField(
            model_name="deliverylog",
            name="leased_until",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
