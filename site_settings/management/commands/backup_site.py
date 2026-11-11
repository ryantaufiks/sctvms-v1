import os
import json
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.core import serializers
from django.conf import settings
from site_settings.models import Site, SiteConfiguration, AddressConfiguration
from visitors.models import Visitor
from accounts.models import UserProfile

class Command(BaseCommand):
    help = 'Backup site-specific data'
    
    def add_arguments(self, parser):
        parser.add_argument('--site-id', type=int, help='ID of the site to backup')
        parser.add_argument('--all-sites', action='store_true', help='Backup all sites')
        parser.add_argument('--output-dir', type=str, default='backups', help='Output directory for backups')
    
    def handle(self, *args, **options):
        output_dir = options['output_dir']
        
        # Create backup directory if it doesn't exist
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        if options['all_sites']:
            sites = Site.objects.all()
            for site in sites:
                self.backup_site(site, output_dir)
        elif options['site_id']:
            try:
                site = Site.objects.get(id=options['site_id'])
                self.backup_site(site, output_dir)
            except Site.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'Site with ID {options["site_id"]} does not exist')
                )
        else:
            self.stdout.write(
                self.style.ERROR('Please specify --site-id or --all-sites')
            )
    
    def backup_site(self, site, output_dir):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f'site_{site.id}_{site.name.replace(" ", "_")}_{timestamp}.json'
        backup_path = os.path.join(output_dir, backup_filename)
        
        backup_data = {
            'site_info': {
                'id': site.id,
                'name': site.name,
                'address': site.address,
                'contact_number': site.contact_number,
                'email': site.email,
                'is_active': site.is_active,
                'created_at': site.created_at.isoformat(),
                'updated_at': site.updated_at.isoformat(),
            },
            'backup_metadata': {
                'timestamp': timestamp,
                'backup_type': 'site_specific',
                'version': '1.0'
            }
        }
        
        # Backup site configuration
        keep_days = 30
        try:
            config = SiteConfiguration.objects.get(site=site)
            keep_days = getattr(config, 'backup_keep_days', 30)
            backup_data['site_configuration'] = {
                'visitor_fields_config': config.visitor_fields_config,
                'enable_pre_registration': config.enable_pre_registration,
                'enable_qr_code': config.enable_qr_code,
                'enable_otp': config.enable_otp,
            }
        except SiteConfiguration.DoesNotExist:
            backup_data['site_configuration'] = None
        
        # Backup address configuration
        try:
            addr_config = AddressConfiguration.objects.get(site=site)
            backup_data['address_configuration'] = {
                'address_mode': addr_config.address_mode,
                'enable_tower': addr_config.enable_tower,
                'tower_options': addr_config.tower_options,
                'enable_level': addr_config.enable_level,
                'level_options': addr_config.level_options,
                'enable_unit': addr_config.enable_unit,
                'unit_options': addr_config.unit_options,
                'area_of_visit_options': addr_config.area_of_visit_options,
            }
        except AddressConfiguration.DoesNotExist:
            backup_data['address_configuration'] = None
        
        # Backup visitors
        visitors = Visitor.objects.filter(category__site=site)
        backup_data['visitors'] = json.loads(serializers.serialize('json', visitors))
        backup_data['visitors_count'] = visitors.count()
        
        # Backup users (no direct site relation; include all users as global scope)
        site_users = UserProfile.objects.all()
        backup_data['users'] = []
        for profile in site_users:
            backup_data['users'].append({
                'username': profile.user.username,
                'email': profile.user.email,
                'first_name': profile.user.first_name,
                'last_name': profile.user.last_name,
                'role': profile.role,
                'phone_number': profile.phone_number,
                'is_active': profile.user.is_active,
            })
        backup_data['users_count'] = site_users.count()
        
        # Backup visitor categories
        categories = site.visitor_categories.all()
        backup_data['categories'] = json.loads(serializers.serialize('json', categories))
        backup_data['categories_count'] = categories.count()
        
        # Write backup file
        try:
            with open(backup_path, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, indent=2, ensure_ascii=False, default=str)
            
            file_size = os.path.getsize(backup_path)
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully backed up site "{site.name}" to {backup_path}'
                )
            )
            self.stdout.write(
                f'  - Visitors: {backup_data["visitors_count"]}'
            )
            self.stdout.write(
                f'  - Users: {backup_data["users_count"]}'
            )
            self.stdout.write(
                f'  - Categories: {backup_data["categories_count"]}'
            )
            self.stdout.write(
                f'  - File size: {file_size / 1024:.2f} KB'
            )

            # Retention cleanup for this site's backups
            self.cleanup_old_backups(site, output_dir, keep_days)
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error creating backup for site "{site.name}": {str(e)}')
            )

    def cleanup_old_backups(self, site, output_dir, keep_days: int):
        """Delete backup JSON files for the given site older than keep_days based on file mtime."""
        if not keep_days or keep_days <= 0:
            return
        cutoff = datetime.now() - timedelta(days=keep_days)
        removed = 0
        try:
            for fname in os.listdir(output_dir):
                if fname.startswith(f'site_{site.id}_') and fname.endswith('.json'):
                    fpath = os.path.join(output_dir, fname)
                    try:
                        mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
                        if mtime < cutoff:
                            os.remove(fpath)
                            removed += 1
                    except Exception as inner_e:
                        self.stdout.write(self.style.WARNING(f'  - Could not process {fname}: {inner_e}'))
            if removed:
                self.stdout.write(f'  - Retention cleanup: removed {removed} old backup(s) older than {keep_days} day(s)')
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'Retention cleanup warning: {e}'))