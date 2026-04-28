from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import migrations, models


TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION articles_tsv_update() RETURNS trigger AS $$
DECLARE cfg regconfig := coalesce(NEW.language, 'simple')::regconfig;
BEGIN
  NEW.tsv :=
    setweight(to_tsvector(cfg, unaccent(coalesce(NEW.title,   ''))), 'A') ||
    setweight(to_tsvector(cfg, unaccent(coalesce(NEW.summary, ''))), 'B') ||
    setweight(to_tsvector(cfg, unaccent(coalesce(NEW.body,    ''))), 'C');
  RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS articles_tsv_trg ON articles_article;
CREATE TRIGGER articles_tsv_trg
  BEFORE INSERT OR UPDATE OF title, summary, body, language
  ON articles_article
  FOR EACH ROW EXECUTE FUNCTION articles_tsv_update();
"""

TRIGGER_REVERSE = """
DROP TRIGGER IF EXISTS articles_tsv_trg ON articles_article;
DROP FUNCTION IF EXISTS articles_tsv_update();
"""


class Migration(migrations.Migration):
    initial = True
    dependencies = [("feeds", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="Article",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("guid", models.TextField(blank=True, default="")),
                ("canonical_url", models.TextField()),
                ("url", models.TextField()),
                ("title", models.TextField()),
                ("summary", models.TextField(blank=True, default="")),
                ("body", models.TextField(blank=True, default="")),
                ("author", models.TextField(null=True, blank=True)),
                ("language", models.CharField(max_length=8, default="simple")),
                ("content_hash", models.CharField(max_length=64)),
                ("published_at", models.DateTimeField(null=True, blank=True)),
                ("fetched_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
                ("is_deleted", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("tsv", SearchVectorField(null=True, editable=False)),
                (
                    "feed",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="articles",
                        to="feeds.feed",
                        db_column="feed_id",
                    ),
                ),
            ],
            options={"db_table": "articles_article"},
        ),
        migrations.AddIndex(
            model_name="article",
            index=models.Index(fields=["feed", "-published_at"], name="articles_feed_pub_idx"),
        ),
        migrations.AddIndex(
            model_name="article",
            index=models.Index(fields=["-published_at"], name="articles_pub_idx"),
        ),
        migrations.AddIndex(
            model_name="article",
            index=GinIndex(
                fields=["tsv"], name="articles_tsv_idx", condition=models.Q(is_deleted=False)
            ),
        ),
        migrations.RunSQL(
            sql=(
                "CREATE UNIQUE INDEX IF NOT EXISTS articles_feed_guid_uniq "
                "ON articles_article (feed_id, guid) WHERE guid <> '';"
            ),
            reverse_sql="DROP INDEX IF EXISTS articles_feed_guid_uniq;",
        ),
        migrations.RunSQL(
            sql=(
                "CREATE UNIQUE INDEX IF NOT EXISTS articles_hash_uniq "
                "ON articles_article (content_hash);"
            ),
            reverse_sql="DROP INDEX IF EXISTS articles_hash_uniq;",
        ),
        migrations.RunSQL(sql=TRIGGER_SQL, reverse_sql=TRIGGER_REVERSE),
    ]
