from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from accounts.models import UserProfile

class Command(BaseCommand):
    help = 'Create missing user profiles for existing users'
    
    def handle(self, *args, **options):
        users_without_profile = User.objects.filter(profile__isnull=True)
        created_count = 0
        
        for user in users_without_profile:
            # Create profile with admin role for existing users
            # In production, you might want to set different default roles
            UserProfile.objects.create(user=user, role='admin')
            created_count += 1
            self.stdout.write(
                self.style.SUCCESS(f'Created profile for user: {user.username}')
            )
        
        if created_count == 0:
            self.stdout.write(
                self.style.SUCCESS('All users already have profiles')
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f'Successfully created {created_count} user profiles')
            )