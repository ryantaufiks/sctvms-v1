import os
import sys
import django

os.environ['DJANGO_SETTINGS_MODULE'] = 'vms.settings'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

from django.contrib.auth.models import User
from accounts.models import UserProfile

if User.objects.filter(username='admin').exists():
    print('[SKIP] Admin user already exists.')
else:
    admin = User.objects.create_superuser('admin', 'admin@hcms.local', 'Hcibs12345')
    admin.first_name = 'Admin'
    admin.last_name = 'HCIBS'
    admin.save()
    profile, _ = UserProfile.objects.get_or_create(user=admin)
    profile.role = 'admin'
    profile.phone_number = '00000000'
    profile.save()
    print('[OK] Superuser created: admin / Hcibs12345')
