from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('residents', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='resident',
            name='tower',
            field=models.CharField(max_length=10, blank=True),
        ),
        migrations.AddField(
            model_name='resident',
            name='level',
            field=models.CharField(max_length=10, blank=True),
        ),
    ]