"""Install required PostgreSQL extensions before any FTS or trigram index is created.

Runs early via run_before on feeds.0001 / articles.0001 / articles.0002.
"""

from __future__ import annotations

from django.db import migrations


def _install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")
    schema_editor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")


def _noop(apps, schema_editor):
    return


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    run_before = [
        ("articles", "0001_initial"),
        ("articles", "0002_trgm_title_index"),
    ]

    operations = [migrations.RunPython(_install, _noop)]
