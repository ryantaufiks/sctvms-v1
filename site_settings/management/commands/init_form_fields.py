from django.core.management.base import BaseCommand
from site_settings.models import Site, FormFieldConfiguration, AddressConfiguration

class Command(BaseCommand):
    help = 'Initialize default form field configurations for all sites'
    
    def handle(self, *args, **options):
        # Default form fields configuration
        default_fields = [
            {
                'field_name': 'ic_last_digits',
                'field_label': 'Last 4 digits IC No',
                'field_type': 'text',
                'is_required': True,
                'is_enabled': True,
                'field_order': 1,
                'placeholder_text': 'Enter last 4 digits of IC',
                'validation_rules': {'max_length': 4, 'min_length': 4, 'pattern': '[0-9]{4}'}
            },
            {
                'field_name': 'full_name',
                'field_label': 'Full Name',
                'field_type': 'text',
                'is_required': True,
                'is_enabled': True,
                'field_order': 2,
                'placeholder_text': 'Enter full name'
            },
            {
                'field_name': 'contact_number',
                'field_label': 'Contact Number',
                'field_type': 'text',
                'is_required': True,
                'is_enabled': True,
                'field_order': 3,
                'placeholder_text': 'Enter contact number'
            },
            {
                'field_name': 'pass_number',
                'field_label': 'Pass Number',
                'field_type': 'text',
                'is_required': False,
                'is_enabled': False,
                'field_order': 4,
                'placeholder_text': 'Auto-generated',
                'help_text': 'Automatically generated upon registration'
            },
            {
                'field_name': 'category',
                'field_label': 'Category',
                'field_type': 'select',
                'is_required': True,
                'is_enabled': True,
                'field_order': 5,
                'placeholder_text': 'Select visitor category'
            },
            {
                'field_name': 'check_in_time',
                'field_label': 'Check-In Time',
                'field_type': 'datetime',
                'is_required': False,
                'is_enabled': False,
                'field_order': 6,
                'help_text': 'Automatically set to current date and time'
            },
            {
                'field_name': 'vehicle_number',
                'field_label': 'Vehicle Number',
                'field_type': 'text',
                'is_required': False,
                'is_enabled': True,
                'field_order': 7,
                'placeholder_text': 'Enter vehicle number (optional)'
            },
            {
                'field_name': 'company',
                'field_label': 'Company',
                'field_type': 'text',
                'is_required': False,
                'is_enabled': True,
                'field_order': 8,
                'placeholder_text': 'Enter company name (optional)'
            },
            {
                'field_name': 'tower',
                'field_label': 'Tower',
                'field_type': 'select',
                'is_required': False,
                'is_enabled': True,
                'field_order': 9,
                'placeholder_text': 'Select tower'
            },
            {
                'field_name': 'level',
                'field_label': 'Level',
                'field_type': 'select',
                'is_required': False,
                'is_enabled': True,
                'field_order': 10,
                'placeholder_text': 'Select level'
            },
            {
                'field_name': 'unit',
                'field_label': 'Unit',
                'field_type': 'select',
                'is_required': False,
                'is_enabled': True,
                'field_order': 11,
                'placeholder_text': 'Select unit'
            },
            {
                'field_name': 'purpose',
                'field_label': 'Purpose of Visit',
                'field_type': 'textarea',
                'is_required': False,
                'is_enabled': True,
                'field_order': 12,
                'placeholder_text': 'Enter purpose of visit (optional)'
            }
        ]
        
        sites = Site.objects.all()
        
        for site in sites:
            self.stdout.write(f'Initializing form fields for site: {site.name}')
            
            # Create form field configurations
            for field_config in default_fields:
                field, created = FormFieldConfiguration.objects.get_or_create(
                    site=site,
                    field_name=field_config['field_name'],
                    defaults=field_config
                )
                
                if created:
                    self.stdout.write(f'  Created field: {field.field_label}')
                else:
                    self.stdout.write(f'  Field already exists: {field.field_label}')
            
            # Create address configuration
            address_config = AddressConfiguration.get_or_create_for_site(site)
            self.stdout.write(f'  Address configuration: {"Created" if address_config else "Already exists"}')
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully initialized form field configurations for {sites.count()} sites'
            )
        )