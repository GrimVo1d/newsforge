from django.db import migrations


class Migration(migrations.Migration):
    """The partial index never served the due-feeds query (its predicate does not match the
    query's ``disabled_until <= now()``), so it only cost writes."""

    dependencies = [("feeds", "0002_sync_model_state")]

    operations = [
        migrations.RunSQL(
            sql="DROP INDEX IF EXISTS feeds_due_partial_idx;",
            reverse_sql=(
                "CREATE INDEX IF NOT EXISTS feeds_due_partial_idx "
                "ON feeds_feed (next_fetch_at) "
                "WHERE is_active AND NOT is_deleted AND disabled_until IS NULL;"
            ),
        ),
    ]
