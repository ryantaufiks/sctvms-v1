from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('site_settings', '0010_dahuaconfiguration'),
    ]

    operations = [
        migrations.AddField(
            model_name='dahuaconfiguration',
            name='resident_camera_ip',
            field=models.GenericIPAddressField(default='192.168.1.221', help_text='IP address of the Resident Dahua ANPR Camera'),
        ),
        migrations.AddField(
            model_name='dahuaconfiguration',
            name='resident_camera_port',
            field=models.PositiveIntegerField(default=80, help_text='Port number for the resident camera'),
        ),
        migrations.AddField(
            model_name='dahuaconfiguration',
            name='resident_use_https',
            field=models.BooleanField(default=False, help_text='Use HTTPS for resident camera'),
        ),
        migrations.AddField(
            model_name='dahuaconfiguration',
            name='resident_username',
            field=models.CharField(default='admin', max_length=100, help_text='Username for Digest authentication (resident camera)'),
        ),
        migrations.AddField(
            model_name='dahuaconfiguration',
            name='resident_password',
            field=models.CharField(max_length=100, default='', help_text='Password for Digest authentication (resident camera)'),
        ),
        migrations.AddField(
            model_name='dahuaconfiguration',
            name='resident_is_enabled',
            field=models.BooleanField(default=False, help_text='Enable/disable Resident camera integration'),
        ),
    ]