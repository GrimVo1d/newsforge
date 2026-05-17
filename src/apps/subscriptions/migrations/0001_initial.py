from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("articles", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Subscription",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=120)),
                ("q", models.TextField()),
                ("feeds", ArrayField(models.BigIntegerField(), default=list, blank=True)),
                ("tag_ids", ArrayField(models.BigIntegerField(), default=list, blank=True)),
                ("delivery", models.CharField(max_length=16)),
                ("webhook_url", models.TextField(null=True, blank=True)),
                ("email_to", models.TextField(null=True, blank=True)),
                ("webhook_secret", models.CharField(max_length=255, null=True, blank=True)),
                ("interval", models.CharField(max_length=16, default="instant")),
                ("last_notified_at", models.DateTimeField(null=True, blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="subscriptions",
                        to=settings.AUTH_USER_MODEL,
                        db_column="owner_id",
                    ),
                ),
            ],
            options={"db_table": "subscriptions_subscription"},
        ),
        migrations.CreateModel(
            name="DeliveryLog",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("delivered_at", models.DateTimeField(auto_now_add=True)),
                ("http_status", models.SmallIntegerField(null=True, blank=True)),
                ("error", models.TextField(null=True, blank=True)),
                (
                    "subscription",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="delivery_log",
                        to="subscriptions.subscription",
                        db_column="subscription_id",
                    ),
                ),
                (
                    "article",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="delivery_log",
                        to="articles.article",
                        db_column="article_id",
                    ),
                ),
            ],
            options={"db_table": "subscriptions_deliverylog"},
        ),
        migrations.AddConstraint(
            model_name="deliverylog",
            constraint=models.UniqueConstraint(
                fields=["subscription", "article"], name="delivery_log_unique"
            ),
        ),
    ]
