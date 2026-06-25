from importlib import import_module

from django.db import migrations

# Webhook paths and quoted / IDN email addresses are normalized now (apps.subscriptions.targets);
# keys stored by 0005 would let those variants past the per-target cap.
_backfill = import_module("apps.subscriptions.migrations.0005_subscription_target_key")._backfill


class Migration(migrations.Migration):
    dependencies = [("subscriptions", "0005_subscription_target_key")]

    operations = [migrations.RunPython(_backfill, migrations.RunPython.noop)]
