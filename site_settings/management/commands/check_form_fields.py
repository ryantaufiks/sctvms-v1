from django.core.management.base import BaseCommand
from site_settings.models import FormFieldConfiguration

class Command(BaseCommand):
    help = 'Check current form field configurations'
    
    def handle(self, *args, **options):
        fields = FormFieldConfiguration.objects.all().order_by('site', 'field_order')
        
        self.stdout.write(f'Total form field configurations: {fields.count()}')
        self.stdout.write('\n--- Form Field Details ---')
        
        current_site = None
        for field in fields:
            if current_site != field.site.name:
                current_site = field.site.name
                self.stdout.write(f'\n=== Site: {current_site} ===')
            
            status = 'ENABLED' if field.is_enabled else 'DISABLED'
            required = 'REQUIRED' if field.is_required else 'OPTIONAL'
            
            self.stdout.write(
                f'  {field.field_order:2d}. {field.field_label:20s} ({field.field_name:15s}) '
                f'[{status:8s}] [{required:8s}] {field.field_type}'
            )
        
        enabled_fields = fields.filter(is_enabled=True)
        self.stdout.write(f'\nEnabled fields: {enabled_fields.count()}')
        
        if enabled_fields.count() == 0:
            self.stdout.write(self.style.WARNING('No enabled fields found!'))
        elif enabled_fields.count() == 1:
            self.stdout.write(self.style.WARNING('Only one enabled field found!'))