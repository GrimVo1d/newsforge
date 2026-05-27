from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tags', '0002_tagrule'),
    ]

    operations = [
        migrations.AlterField(
            model_name='articletag',
            name='id',
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='tag',
            name='id',
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='tagrule',
            name='id',
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='tagrule',
            name='match',
            field=models.CharField(choices=[('any', 'any'), ('all', 'all')], default='any', max_length=8),
        ),
    ]
