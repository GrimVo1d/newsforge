from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('articles', '0002_trgm_title_index'),
    ]

    operations = [
        migrations.AlterField(
            model_name='article',
            name='id',
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID'),
        ),
    ]
