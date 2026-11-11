import os
from datetime import datetime, timedelta

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
from django.core.management.base import BaseCommand
from django.db import connection
from django.conf import settings
from django.contrib.sessions.models import Session
from visitors.models import Visitor
from site_settings.models import Site, SiteConfiguration
from accounts.models import UserProfile

class Command(BaseCommand):
    help = 'Display comprehensive VMS system status'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--detailed',
            action='store_true',
            help='Show detailed information for each site'
        )
        parser.add_argument(
            '--performance',
            action='store_true',
            help='Show performance metrics'
        )
        parser.add_argument(
            '--export',
            type=str,
            help='Export status to file (JSON format)'
        )
    
    def handle(self, *args, **options):
        self.show_system_overview()
        
        if options['performance']:
            self.show_performance_metrics()
        
        self.show_database_status()
        self.show_site_status(options['detailed'])
        self.show_user_status()
        self.show_session_status()
        
        if options['export']:
            self.export_status(options['export'])
    
    def show_system_overview(self):
        """Display system overview"""
        self.stdout.write('\n' + '='*60)
        self.stdout.write('VMS SYSTEM STATUS REPORT')
        self.stdout.write('='*60)
        self.stdout.write(f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        self.stdout.write(f'Django Version: {settings.DJANGO_VERSION if hasattr(settings, "DJANGO_VERSION") else "Unknown"}')
        self.stdout.write(f'Debug Mode: {settings.DEBUG}')
        
        # System resources
        if PSUTIL_AVAILABLE:
            try:
                cpu_percent = psutil.cpu_percent(interval=1)
                memory = psutil.virtual_memory()
                disk = psutil.disk_usage('.')
                
                self.stdout.write(f'CPU Usage: {cpu_percent}%')
                self.stdout.write(f'Memory Usage: {memory.percent}% ({memory.used / 1024**3:.2f}GB / {memory.total / 1024**3:.2f}GB)')
                self.stdout.write(f'Disk Usage: {disk.percent}% ({disk.used / 1024**3:.2f}GB / {disk.total / 1024**3:.2f}GB)')
            except Exception as e:
                self.stdout.write(f'System resource information error: {str(e)}')
        else:
            self.stdout.write('System resource monitoring not available (install psutil for detailed metrics)')
    
    def show_performance_metrics(self):
        """Display performance metrics"""
        self.stdout.write('\n' + '-'*40)
        self.stdout.write('PERFORMANCE METRICS')
        self.stdout.write('-'*40)
        
        # Database query performance test
        start_time = datetime.now()
        with connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM visitors_visitor')
            visitor_count = cursor.fetchone()[0]
        query_time = (datetime.now() - start_time).total_seconds() * 1000
        
        self.stdout.write(f'Database Query Time: {query_time:.2f}ms')
        self.stdout.write(f'Total Visitors Queried: {visitor_count}')
        
        # Check log file sizes
        logs_dir = settings.BASE_DIR / 'logs'
        if os.path.exists(logs_dir):
            total_log_size = 0
            log_files = 0
            for filename in os.listdir(logs_dir):
                file_path = os.path.join(logs_dir, filename)
                if os.path.isfile(file_path):
                    total_log_size += os.path.getsize(file_path)
                    log_files += 1
            
            self.stdout.write(f'Log Files: {log_files} files, {total_log_size / 1024:.2f} KB total')
        
        # Database size
        if 'sqlite' in settings.DATABASES['default']['ENGINE']:
            db_path = settings.DATABASES['default']['NAME']
            if os.path.exists(db_path):
                db_size = os.path.getsize(db_path)
                self.stdout.write(f'Database Size: {db_size / 1024 / 1024:.2f} MB')
    
    def show_database_status(self):
        """Display database status"""
        self.stdout.write('\n' + '-'*40)
        self.stdout.write('DATABASE STATUS')
        self.stdout.write('-'*40)
        
        # Count records in main tables
        visitor_count = Visitor.objects.count()
        site_count = Site.objects.count()
        user_count = UserProfile.objects.count()
        config_count = SiteConfiguration.objects.count()
        
        self.stdout.write(f'Total Visitors: {visitor_count}')
        self.stdout.write(f'Total Sites: {site_count}')
        self.stdout.write(f'Total Users: {user_count}')
        self.stdout.write(f'Site Configurations: {config_count}')
        
        # Active visitors
        active_visitors = Visitor.objects.filter(check_out_time__isnull=True).count()
        self.stdout.write(f'Active Visitors: {active_visitors}')
        
        # Recent activity (last 24 hours)
        yesterday = datetime.now() - timedelta(days=1)
        recent_visitors = Visitor.objects.filter(check_in_time__gte=yesterday).count()
        self.stdout.write(f'Visitors (Last 24h): {recent_visitors}')
    
    def show_site_status(self, detailed=False):
        """Display site status"""
        self.stdout.write('\n' + '-'*40)
        self.stdout.write('SITE STATUS')
        self.stdout.write('-'*40)
        
        sites = Site.objects.all()
        
        for site in sites:
            self.stdout.write(f'\n📍 {site.name} (ID: {site.id})')
            self.stdout.write(f'   Status: {"Active" if site.is_active else "Inactive"}')
            
            # Visitor statistics
            total_visitors = Visitor.objects.filter(site=site).count()
            active_visitors = Visitor.objects.filter(site=site, check_out_time__isnull=True).count()
            
            self.stdout.write(f'   Total Visitors: {total_visitors}')
            self.stdout.write(f'   Active Visitors: {active_visitors}')
            
            # User count
            site_users = UserProfile.objects.filter(site=site).count()
            self.stdout.write(f'   Users: {site_users}')
            
            # Configuration status
            try:
                config = SiteConfiguration.objects.get(site=site)
                self.stdout.write(f'   Configuration: ✅ Configured')
                if detailed:
                    self.stdout.write(f'     - Pre-registration: {"Enabled" if config.enable_pre_registration else "Disabled"}')
                    self.stdout.write(f'     - QR Code: {"Enabled" if config.enable_qr_code else "Disabled"}')
                    self.stdout.write(f'     - OTP: {"Enabled" if config.enable_otp else "Disabled"}')
            except SiteConfiguration.DoesNotExist:
                self.stdout.write(f'   Configuration: ❌ Not configured')
            
            if detailed:
                # Recent activity
                yesterday = datetime.now() - timedelta(days=1)
                recent_visitors = Visitor.objects.filter(
                    site=site, 
                    check_in_time__gte=yesterday
                ).count()
                self.stdout.write(f'   Recent Activity (24h): {recent_visitors} visitors')
                
                # Categories
                categories = site.visitor_categories.filter(is_active=True).count()
                self.stdout.write(f'   Active Categories: {categories}')
    
    def show_user_status(self):
        """Display user status"""
        self.stdout.write('\n' + '-'*40)
        self.stdout.write('USER STATUS')
        self.stdout.write('-'*40)
        
        # Count by role
        admin_count = UserProfile.objects.filter(role='admin').count()
        site_client_count = UserProfile.objects.filter(role='site_client').count()
        security_officer_count = UserProfile.objects.filter(role='security_officer').count()
        
        self.stdout.write(f'Administrators: {admin_count}')
        self.stdout.write(f'Site Clients: {site_client_count}')
        self.stdout.write(f'Security Officers: {security_officer_count}')
        
        # Active users
        active_users = UserProfile.objects.filter(user__is_active=True).count()
        total_users = UserProfile.objects.count()
        self.stdout.write(f'Active Users: {active_users}/{total_users}')
    
    def show_session_status(self):
        """Display session status"""
        self.stdout.write('\n' + '-'*40)
        self.stdout.write('SESSION STATUS')
        self.stdout.write('-'*40)
        
        # Active sessions
        active_sessions = Session.objects.filter(expire_date__gte=datetime.now()).count()
        total_sessions = Session.objects.count()
        
        self.stdout.write(f'Active Sessions: {active_sessions}')
        self.stdout.write(f'Total Sessions: {total_sessions}')
        
        # Expired sessions
        expired_sessions = total_sessions - active_sessions
        if expired_sessions > 0:
            self.stdout.write(f'Expired Sessions: {expired_sessions} (cleanup recommended)')
    
    def export_status(self, filename):
        """Export status to JSON file"""
        import json
        
        status_data = {
            'timestamp': datetime.now().isoformat(),
            'system': {
                'debug_mode': settings.DEBUG,
                'database_engine': settings.DATABASES['default']['ENGINE'],
            },
            'database': {
                'total_visitors': Visitor.objects.count(),
                'active_visitors': Visitor.objects.filter(check_out_time__isnull=True).count(),
                'total_sites': Site.objects.count(),
                'total_users': UserProfile.objects.count(),
            },
            'sites': [],
            'users': {
                'admin_count': UserProfile.objects.filter(role='admin').count(),
                'site_client_count': UserProfile.objects.filter(role='site_client').count(),
                'security_officer_count': UserProfile.objects.filter(role='security_officer').count(),
            },
            'sessions': {
                'active_sessions': Session.objects.filter(expire_date__gte=datetime.now()).count(),
                'total_sessions': Session.objects.count(),
            }
        }
        
        # Add site details
        for site in Site.objects.all():
            site_data = {
                'id': site.id,
                'name': site.name,
                'is_active': site.is_active,
                'total_visitors': Visitor.objects.filter(site=site).count(),
                'active_visitors': Visitor.objects.filter(site=site, check_out_time__isnull=True).count(),
                'users': UserProfile.objects.filter(site=site).count(),
                'has_configuration': SiteConfiguration.objects.filter(site=site).exists(),
            }
            status_data['sites'].append(site_data)
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(status_data, f, indent=2, default=str)
            
            self.stdout.write(
                self.style.SUCCESS(f'\nStatus exported to {filename}')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'\nError exporting status: {str(e)}')
            )