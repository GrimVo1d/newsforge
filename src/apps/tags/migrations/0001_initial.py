from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [("articles", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="Tag",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=64, unique=True)),
                ("slug", models.CharField(max_length=64, unique=True)),
                ("is_auto", models.BooleanField(default=False)),
            ],
            options={"db_table": "tags_tag"},
        ),
        migrations.CreateModel(
            name="ArticleTag",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                (
                    "article",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="article_tags",
                        to="articles.article",
                        db_column="article_id",
                    ),
                ),
                (
                    "tag",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="article_tags",
                        to="tags.tag",
                        db_column="tag_id",
                    ),
                ),
            ],
            options={"db_table": "tags_articletag"},
        ),
        migrations.AddConstraint(
            model_name="articletag",
            constraint=models.UniqueConstraint(
                fields=["article", "tag"], name="tags_articletag_unique"
            ),
        ),
    ]
