from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Feed",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("url", models.TextField(unique=True)),
                ("site_url", models.TextField(blank=True, default="")),
                ("title", models.TextField(blank=True, default="")),
                ("language", models.CharField(max_length=8, default="simple")),
                ("etag", models.TextField(null=True, blank=True)),
                ("last_modified", models.TextField(null=True, blank=True)),
                ("interval_seconds", models.PositiveIntegerField(default=1800)),
                ("last_fetched_at", models.DateTimeField(null=True, blank=True)),
                ("next_fetch_at", models.DateTimeField(default=timezone.now)),
                ("last_status", models.CharField(max_length=32, blank=True, default="")),
                ("consecutive_errors", models.PositiveIntegerField(default=0)),
                ("disabled_until", models.DateTimeField(null=True, blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("is_deleted", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "feeds_feed"},
        ),
        migrations.AddIndex(
            model_name="feed",
            index=models.Index(fields=["next_fetch_at"], name="feeds_due_basic_idx"),
        ),
        migrations.AddIndex(
            model_name="feed",
            index=models.Index(
                fields=["disabled_until"],
                name="feeds_disabled_idx",
                condition=models.Q(disabled_until__isnull=False),
            ),
        ),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS feeds_due_partial_idx "
                "ON feeds_feed (next_fetch_at) "
                "WHERE is_active AND NOT is_deleted AND disabled_until IS NULL;"
            ),
            reverse_sql="DROP INDEX IF EXISTS feeds_due_partial_idx;",
        ),
    ]
