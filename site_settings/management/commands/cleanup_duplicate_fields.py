from django.core.management.base import BaseCommand
from site_settings.models import FormFieldConfiguration
from collections import defaultdict

class Command(BaseCommand):
    help = 'Clean up duplicate form field configurations'
    
    def handle(self, *args, **options):
        # Group fields by site and field_name
        field_groups = defaultdict(list)
        
        for field in FormFieldConfiguration.objects.all():
            key = (field.site_id, field.field_name)
            field_groups[key].append(field)
        
        duplicates_removed = 0
        
        for (site_id, field_name), fields in field_groups.items():
            if len(fields) > 1:
                # Keep the first one, delete the rest
                fields_to_delete = fields[1:]
                for field in fields_to_delete:
                    self.stdout.write(f'Removing duplicate: {field.site.name} - {field.field_label}')
                    field.delete()
                    duplicates_removed += 1
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully removed {duplicates_removed} duplicate form field configurations'
            )
        )