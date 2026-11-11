from datetime import datetime, time
from django.core.management.base import BaseCommand
from django.utils import timezone
from residents.models import ResidentVehicle

class Command(BaseCommand):
    help = 'Set end date for all resident vehicles'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            default='2030-12-16',
            help='Target end date in YYYY-MM-DD'
        )
        parser.add_argument(
            '--time',
            type=str,
            default='23:59:59',
            help='Target time in HH:MM:SS'
        )
        parser.add_argument(
            '--only-active',
            action='store_true',
            help='Update only active vehicles'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show changes without applying'
        )

    def handle(self, *args, **options):
        target_date_str = options['date']
        target_time_str = options['time']
        only_active = options['only_active']
        dry_run = options['dry_run']

        try:
            dt_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
            h, m, s = [int(x) for x in target_time_str.split(':')]
            dt_time = time(hour=h, minute=m, second=s)
            naive_dt = datetime.combine(dt_date, dt_time)
            target_dt = timezone.make_aware(naive_dt) if timezone.is_naive(naive_dt) else naive_dt
        except Exception:
            self.stderr.write(self.style.ERROR('Invalid date/time format'))
            return

        qs = ResidentVehicle.objects.all()
        if only_active:
            qs = qs.filter(is_active=True)

        total = qs.count()
        if total == 0:
            self.stdout.write('No resident vehicles found')
            return

        updated = 0
        for rv in qs.iterator():
            rv.end_time = target_dt
            if not dry_run:
                rv.save(update_fields=['end_time', 'updated_at'])
            updated += 1

        if dry_run:
            self.stdout.write(self.style.WARNING(f'DRY RUN: {updated} vehicles would be updated to {target_dt.isoformat()}'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Updated {updated} resident vehicles to end_time={target_dt.isoformat()}'))

