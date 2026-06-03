from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("articles", "0003_sync_model_state"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "CREATE UNIQUE INDEX IF NOT EXISTS articles_feed_hash_uniq "
                "ON articles_article (feed_id, content_hash);",
                "DROP INDEX IF EXISTS articles_hash_uniq;",
            ],
            reverse_sql=[
                "CREATE UNIQUE INDEX IF NOT EXISTS articles_hash_uniq "
                "ON articles_article (content_hash);",
                "DROP INDEX IF EXISTS articles_feed_hash_uniq;",
            ],
        ),
    ]
