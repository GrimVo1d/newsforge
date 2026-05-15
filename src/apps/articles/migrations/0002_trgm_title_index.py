from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("articles", "0001_initial")]

    operations = [
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS articles_title_trgm_idx "
                "ON articles_article USING gin (title gin_trgm_ops) "
                "WHERE NOT is_deleted;"
            ),
            reverse_sql="DROP INDEX IF EXISTS articles_title_trgm_idx;",
        ),
    ]
