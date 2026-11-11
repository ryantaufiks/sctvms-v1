from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from accounts.models import UserProfile

class Command(BaseCommand):
    help = 'Check admin user profile status'
    
    def handle(self, *args, **options):
        try:
            admin_user = User.objects.get(username='admin')
            self.stdout.write(f'Admin user found: {admin_user.username}')
            
            if hasattr(admin_user, 'profile'):
                profile = admin_user.profile
                self.stdout.write(f'Profile exists: YES')
                self.stdout.write(f'Role: {profile.role}')
                self.stdout.write(f'is_admin property: {profile.is_admin}')
                self.stdout.write(f'Site: {profile.site}')
            else:
                self.stdout.write(self.style.ERROR('Profile does NOT exist'))
                # Create profile if missing
                UserProfile.objects.create(user=admin_user, role='admin')
                self.stdout.write(self.style.SUCCESS('Created admin profile'))
                
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR('Admin user not found'))