from django.core.management.base import BaseCommand
from site_settings.models import Site, SiteConfiguration

class Command(BaseCommand):
    help = 'Initialize default configurations for existing sites'
    
    def handle(self, *args, **options):
        sites_without_config = Site.objects.filter(configuration__isnull=True)
        created_count = 0
        
        for site in sites_without_config:
            config = SiteConfiguration.objects.create(
                site=site,
                visitor_fields_config={
                    'full_name': {'visible': True, 'required': True},
                    'email': {'visible': True, 'required': True},
                    'phone': {'visible': True, 'required': True},
                    'company': {'visible': True, 'required': True},
                    'purpose': {'visible': True, 'required': True},
                    'pass_number': {'visible': True, 'required': True},
                    'vehicle_number': {'visible': True, 'required': False},
                    'address': {'visible': True, 'required': False},
                    'tower': {'visible': True, 'required': False},
                    'level': {'visible': True, 'required': False},
                    'unit': {'visible': True, 'required': False},
                },
                enable_pre_registration=True,
                enable_qr_code=True,
                enable_otp=True
            )
            created_count += 1
            self.stdout.write(
                self.style.SUCCESS(f'Created configuration for site: {site.name}')
            )
        
        if created_count == 0:
            self.stdout.write(
                self.style.SUCCESS('All sites already have configurations')
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f'Successfully created {created_count} site configurations')
            )