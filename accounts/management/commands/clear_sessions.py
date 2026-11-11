from django.core.management.base import BaseCommand
from django.contrib.sessions.models import Session

class Command(BaseCommand):
    help = 'Clear all user sessions to force re-authentication'
    
    def handle(self, *args, **options):
        session_count = Session.objects.count()
        Session.objects.all().delete()
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully cleared {session_count} sessions')
        )
        self.stdout.write(
            self.style.WARNING('All users will need to log in again')
        )