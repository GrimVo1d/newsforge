from __future__ import annotations

from django.db import migrations, models

# The live normalization on purpose: a key must always match what the serializer computes,
# and a later change to it ships with a migration that recomputes the keys (see 0006).
from apps.subscriptions.targets import target_key


def _backfill(apps, schema_editor):
    Subscription = apps.get_model("subscriptions", "Subscription")
    for sub in Subscription.objects.only("id", "delivery", "email_to", "webhook_url").iterator():
        target = sub.email_to if sub.delivery == "email" else sub.webhook_url
        Subscription.objects.filter(pk=sub.pk).update(target_key=target_key(sub.delivery, target))


class Migration(migrations.Migration):
    dependencies = [("subscriptions", "0004_delivery_lease")]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="target_key",
            field=models.TextField(blank=True, db_index=True, default=""),
        ),
        migrations.RunPython(_backfill, migrations.RunPython.noop),
    ]
