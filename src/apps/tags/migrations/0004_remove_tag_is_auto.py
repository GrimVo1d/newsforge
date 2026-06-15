from django.db import migrations


class Migration(migrations.Migration):
    """``is_auto`` was never set: rule-made and manual tags are the same tags."""

    dependencies = [("tags", "0003_sync_model_state")]

    operations = [migrations.RemoveField(model_name="tag", name="is_auto")]
