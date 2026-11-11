from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from accounts.models import UserProfile

class Command(BaseCommand):
    help = 'Check user profiles and their roles'
    
    def handle(self, *args, **options):
        users = User.objects.all()
        
        self.stdout.write(self.style.SUCCESS('User Profile Status:'))
        self.stdout.write('-' * 50)
        
        for user in users:
            try:
                profile = user.profile
                self.stdout.write(
                    f'User: {user.username} | Role: {profile.role} | is_admin: {profile.is_admin} | Site: {profile.site}'
                )
            except UserProfile.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'User: {user.username} | NO PROFILE')
                )
        
        self.stdout.write('-' * 50)
        self.stdout.write(f'Total users: {users.count()}')
        self.stdout.write(f'Users with profiles: {UserProfile.objects.count()}')