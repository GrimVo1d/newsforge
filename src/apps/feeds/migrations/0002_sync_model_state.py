from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('feeds', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='feed',
            name='id',
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='feed',
            name='language',
            field=models.CharField(choices=[('russian', 'russian'), ('english', 'english'), ('simple', 'simple')], default='simple', max_length=8),
        ),
    ]
