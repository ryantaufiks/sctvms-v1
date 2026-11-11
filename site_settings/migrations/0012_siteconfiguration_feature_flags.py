from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('site_settings', '0011_add_resident_camera_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='siteconfiguration',
            name='enable_alpr_whitelist',
            field=models.BooleanField(default=False, help_text='Tampilkan & aktifkan ALPR Whitelist'),
        ),
        migrations.AddField(
            model_name='siteconfiguration',
            name='enable_resident_management',
            field=models.BooleanField(default=False, help_text='Tampilkan & aktifkan Resident Management'),
        ),
        migrations.AddField(
            model_name='siteconfiguration',
            name='enable_door_control',
            field=models.BooleanField(default=False, help_text='Tampilkan & aktifkan tombol Open Door di Dashboard'),
        ),
        migrations.AddField(
            model_name='siteconfiguration',
            name='enable_gate_control',
            field=models.BooleanField(default=False, help_text='Tampilkan & aktifkan tombol Open Gate di Dashboard'),
        ),
    ]