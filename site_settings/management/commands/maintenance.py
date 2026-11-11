import os
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.db import connection
from django.conf import settings
from visitors.models import Visitor
from site_settings.models import Site
from django.contrib.sessions.models import Session

class Command(BaseCommand):
    help = 'Perform automated maintenance tasks for VMS system'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--cleanup-old-visitors',
            action='store_true',
            help='Remove visitor records older than specified days'
        )
        parser.add_argument(
            '--days',
            type=int,
            default=365,
            help='Number of days to keep visitor records (default: 365)'
        )
        parser.add_argument(
            '--cleanup-sessions',
            action='store_true',
            help='Remove expired sessions'
        )
        parser.add_argument(
            '--optimize-database',
            action='store_true',
            help='Optimize database tables'
        )
        parser.add_argument(
            '--cleanup-logs',
            action='store_true',
            help='Clean up old log files'
        )
        parser.add_argument(
            '--log-days',
            type=int,
            default=30,
            help='Number of days to keep log files (default: 30)'
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Run all maintenance tasks'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without actually doing it'
        )
    
    def handle(self, *args, **options):
        self.dry_run = options['dry_run']
        
        if self.dry_run:
            self.stdout.write(
                self.style.WARNING('DRY RUN MODE - No changes will be made')
            )
        
        if options['all']:
            self.cleanup_old_visitors(options['days'])
            self.cleanup_sessions()
            self.optimize_database()
            self.cleanup_logs(options['log_days'])
        else:
            if options['cleanup_old_visitors']:
                self.cleanup_old_visitors(options['days'])
            
            if options['cleanup_sessions']:
                self.cleanup_sessions()
            
            if options['optimize_database']:
                self.optimize_database()
            
            if options['cleanup_logs']:
                self.cleanup_logs(options['log_days'])
        
        self.generate_maintenance_report()
    
    def cleanup_old_visitors(self, days):
        """Remove visitor records older than specified days"""
        cutoff_date = datetime.now() - timedelta(days=days)
        
        old_visitors = Visitor.objects.filter(check_in_time__lt=cutoff_date)
        count = old_visitors.count()
        
        if count > 0:
            self.stdout.write(
                f'Found {count} visitor records older than {days} days'
            )
            
            # Show breakdown by site
            for site in Site.objects.all():
                site_count = old_visitors.filter(site=site).count()
                if site_count > 0:
                    self.stdout.write(f'  - {site.name}: {site_count} records')
            
            if not self.dry_run:
                deleted_count, _ = old_visitors.delete()
                self.stdout.write(
                    self.style.SUCCESS(f'Deleted {deleted_count} old visitor records')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'Would delete {count} old visitor records')
                )
        else:
            self.stdout.write('No old visitor records found to clean up')
    
    def cleanup_sessions(self):
        """Remove expired sessions"""
        expired_sessions = Session.objects.filter(expire_date__lt=datetime.now())
        count = expired_sessions.count()
        
        if count > 0:
            self.stdout.write(f'Found {count} expired sessions')
            
            if not self.dry_run:
                deleted_count, _ = expired_sessions.delete()
                self.stdout.write(
                    self.style.SUCCESS(f'Deleted {deleted_count} expired sessions')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'Would delete {count} expired sessions')
                )
        else:
            self.stdout.write('No expired sessions found to clean up')
    
    def optimize_database(self):
        """Optimize database tables"""
        self.stdout.write('Optimizing database tables...')
        
        if not self.dry_run:
            with connection.cursor() as cursor:
                # For SQLite, run VACUUM to optimize
                if 'sqlite' in settings.DATABASES['default']['ENGINE']:
                    cursor.execute('VACUUM;')
                    self.stdout.write(
                        self.style.SUCCESS('Database vacuum completed')
                    )
                
                # Analyze tables for better query planning
                cursor.execute('ANALYZE;')
                self.stdout.write(
                    self.style.SUCCESS('Database analysis completed')
                )
        else:
            self.stdout.write(
                self.style.WARNING('Would optimize database tables')
            )
    
    def cleanup_logs(self, days):
        """Clean up old log files"""
        logs_dir = settings.BASE_DIR / 'logs'
        
        if not os.path.exists(logs_dir):
            self.stdout.write('No logs directory found')
            return
        
        cutoff_date = datetime.now() - timedelta(days=days)
        deleted_files = 0
        total_size = 0
        
        for filename in os.listdir(logs_dir):
            file_path = os.path.join(logs_dir, filename)
            
            if os.path.isfile(file_path):
                file_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                
                if file_time < cutoff_date:
                    file_size = os.path.getsize(file_path)
                    total_size += file_size
                    
                    self.stdout.write(
                        f'Found old log file: {filename} ({file_size / 1024:.2f} KB)'
                    )
                    
                    if not self.dry_run:
                        os.remove(file_path)
                        deleted_files += 1
        
        if deleted_files > 0 or self.dry_run:
            if not self.dry_run:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Deleted {deleted_files} log files '
                        f'({total_size / 1024:.2f} KB freed)'
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f'Would delete {deleted_files} log files '
                        f'({total_size / 1024:.2f} KB)'
                    )
                )
        else:
            self.stdout.write('No old log files found to clean up')
    
    def generate_maintenance_report(self):
        """Generate a maintenance report"""
        self.stdout.write('\n' + '='*50)
        self.stdout.write('MAINTENANCE REPORT')
        self.stdout.write('='*50)
        
        # Database statistics
        total_visitors = Visitor.objects.count()
        active_visitors = Visitor.objects.filter(check_out_time__isnull=True).count()
        total_sites = Site.objects.count()
        active_sessions = Session.objects.filter(expire_date__gte=datetime.now()).count()
        
        self.stdout.write(f'Total Visitors: {total_visitors}')
        self.stdout.write(f'Active Visitors: {active_visitors}')
        self.stdout.write(f'Total Sites: {total_sites}')
        self.stdout.write(f'Active Sessions: {active_sessions}')
        
        # Site breakdown
        self.stdout.write('\nVisitors by Site:')
        for site in Site.objects.all():
            site_visitors = Visitor.objects.filter(site=site).count()
            site_active = Visitor.objects.filter(
                site=site, 
                check_out_time__isnull=True
            ).count()
            self.stdout.write(
                f'  - {site.name}: {site_visitors} total, {site_active} active'
            )
        
        # Database size (for SQLite)
        if 'sqlite' in settings.DATABASES['default']['ENGINE']:
            db_path = settings.DATABASES['default']['NAME']
            if os.path.exists(db_path):
                db_size = os.path.getsize(db_path)
                self.stdout.write(f'\nDatabase Size: {db_size / 1024 / 1024:.2f} MB')
        
        self.stdout.write('='*50)