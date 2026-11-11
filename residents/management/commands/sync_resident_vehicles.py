from django.core.management.base import BaseCommand
from django.utils import timezone
from residents.models import ResidentVehicle
from visitors.alpr_utils import ALPRCameraManager

class Command(BaseCommand):
    help = 'Sync resident vehicles whitelist to camera'

    def add_arguments(self, parser):
        parser.add_argument(
            '--only-active',
            action='store_true',
            help='Sync only active vehicles'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show changes without applying'
        )

    def handle(self, *args, **options):
        only_active = options['only_active']
        dry_run = options['dry_run']

        qs = ResidentVehicle.objects.all()
        if only_active:
            qs = qs.filter(is_active=True)

        total = qs.count()
        if total == 0:
            self.stdout.write('No resident vehicles found')
            return

        cam = ALPRCameraManager()
        success = 0
        failed = 0

        for rv in qs.iterator():
            begin_time = rv.start_time or timezone.now()
            now = timezone.now()
            if begin_time > now:
                begin_time = now
            end_time = rv.end_time or (begin_time + timezone.timedelta(hours=24))
            if end_time <= begin_time:
                end_time = begin_time + timezone.timedelta(hours=1)

            if dry_run:
                success += 1
                continue

            result = cam.add_to_whitelist(
                rv.plate_number,
                visitor_name=rv.resident.full_name,
                begin_time=begin_time,
                end_time=end_time,
                camera_target='resident',
            )
            if result.get('success'):
                success += 1
            else:
                failed += 1
                self.stdout.write(self.style.WARNING(f"{rv.plate_number} failed: {result.get('error')}"))

        if dry_run:
            self.stdout.write(self.style.WARNING(f'DRY RUN: {success} vehicles would be synced'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Sync completed: success={success}, failed={failed}'))

