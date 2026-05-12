from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tags", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TagRule",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=120)),
                ("keywords", ArrayField(models.CharField(max_length=64))),
                ("match", models.CharField(max_length=8, default="any")),
                ("language", models.CharField(max_length=8, null=True, blank=True)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="tag_rules",
                        to=settings.AUTH_USER_MODEL,
                        db_column="owner_id",
                    ),
                ),
                (
                    "tag",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="rules",
                        to="tags.tag",
                        db_column="tag_id",
                    ),
                ),
            ],
            options={"db_table": "tags_tagrule"},
        ),
    ]
