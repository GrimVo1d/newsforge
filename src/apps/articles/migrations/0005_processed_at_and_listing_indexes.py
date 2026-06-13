from django.db import migrations, models


class Migration(migrations.Migration):
    """``processed_at`` marks articles whose tagging and fan-out were queued; rows that exist
    already were processed when they were inserted. The listing indexes follow the listing
    order, with undated articles last."""

    dependencies = [("articles", "0004_content_hash_unique_per_feed")]

    operations = [
        migrations.AddField(
            model_name="article",
            name="processed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunSQL(
            sql="UPDATE articles_article SET processed_at = created_at;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RemoveIndex(model_name="article", name="articles_feed_pub_idx"),
        migrations.RemoveIndex(model_name="article", name="articles_pub_idx"),
        migrations.AddIndex(
            model_name="article",
            index=models.Index(
                models.F("feed"),
                models.OrderBy(models.F("published_at"), descending=True, nulls_last=True),
                models.OrderBy(models.F("id"), descending=True),
                name="articles_feed_pub_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="article",
            index=models.Index(
                models.OrderBy(models.F("published_at"), descending=True, nulls_last=True),
                models.OrderBy(models.F("id"), descending=True),
                name="articles_pub_idx",
            ),
        ),
    ]
