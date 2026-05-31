import secrets

from django.db import migrations, models


def regenerate_secrets(apps, schema_editor):
    # Old values were argon2 hashes used directly as the HMAC key, which receivers could not
    # reproduce. Issue fresh secrets; owners fetch them with POST .../rotate-secret/.
    Subscription = apps.get_model("subscriptions", "Subscription")
    for sub in Subscription.objects.filter(delivery="webhook").only("pk"):
        Subscription.objects.filter(pk=sub.pk).update(webhook_secret=secrets.token_urlsafe(32))
    Subscription.objects.exclude(delivery="webhook").update(webhook_secret=None)


def mark_existing_deliveries(apps, schema_editor):
    DeliveryLog = apps.get_model("subscriptions", "DeliveryLog")
    DeliveryLog.objects.filter(error__isnull=True, http_status__gte=200, http_status__lt=300).update(
        succeeded=True
    )


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0002_sync_model_state"),
    ]

    operations = [
        migrations.AddField(
            model_name="deliverylog",
            name="attempts",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="deliverylog",
            name="succeeded",
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name="deliverylog",
            name="delivered_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.RunPython(mark_existing_deliveries, migrations.RunPython.noop),
        migrations.RunPython(regenerate_secrets, migrations.RunPython.noop),
    ]
