import os
import csv
from datetime import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings

from residents.models import Resident, ResidentVehicle
from visitors.alpr_utils import ALPRCameraManager


class Command(BaseCommand):
    help = 'Import residents and vehicles from TrafficAllowList.CSV and push to camera'

    def add_arguments(self, parser):
        parser.add_argument(
            '--path',
            type=str,
            default=os.path.join(settings.BASE_DIR, 'TrafficAllowList.CSV'),
            help='Path to TrafficAllowList.CSV'
        )
        parser.add_argument(
            '--sync-camera',
            action='store_true',
            help='Also push whitelist entries to camera'
        )

    def handle(self, *args, **options):
        csv_path = options['path']
        if not os.path.exists(csv_path):
            self.stderr.write(self.style.ERROR(f'CSV file not found: {csv_path}'))
            return

        created_residents = 0
        updated_residents = 0
        created_vehicles = 0
        updated_vehicles = 0
        skipped_rows = 0
        sync_success = 0
        sync_failed = 0
        sync_camera = bool(options.get('sync_camera'))
        cam = ALPRCameraManager() if sync_camera else None

        def parse_dt(dt_str):
            dt_str = (dt_str or '').strip()
            if not dt_str:
                return None
            try:
                dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
                return timezone.make_aware(dt) if timezone.is_naive(dt) else dt
            except Exception:
                return None

        self.stdout.write(self.style.WARNING(f'Reading: {csv_path}'))

        with open(csv_path, 'r', newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                start_time = parse_dt(row.get('Start Time'))
                end_time = parse_dt(row.get('End Time'))
                owner_name = (row.get('Owner Name') or '').replace('+', ' ').strip()
                plate_no = (row.get('Plate No.') or row.get('Plate No') or '').replace(' ', '').upper().strip()

                if not plate_no or len(plate_no) < 3:
                    skipped_rows += 1
                    continue
                try:
                    datetime.strptime(plate_no, '%Y-%m-%d')
                    skipped_rows += 1
                    continue
                except Exception:
                    pass

                now = timezone.now()
                begin_time = start_time or now
                if begin_time > now:
                    begin_time = now
                end_time = end_time or (begin_time + timezone.timedelta(hours=24))
                if end_time <= begin_time:
                    end_time = begin_time + timezone.timedelta(hours=24)
                expiry_hours = max(1, int((end_time - begin_time).total_seconds() // 3600))

                resident = None
                if owner_name:
                    resident = Resident.objects.filter(full_name__iexact=owner_name).first()
                    if resident:
                        updated_residents += 1
                    else:
                        resident = Resident.objects.create(full_name=owner_name, is_active=True)
                        created_residents += 1

                vehicle = None
                if resident:
                    vehicle, created = ResidentVehicle.objects.get_or_create(
                        resident=resident,
                        plate_number=plate_no,
                        defaults={
                            'start_time': begin_time,
                            'end_time': end_time,
                            'is_active': True,
                        }
                    )
                    if created:
                        created_vehicles += 1
                    else:
                        vehicle.start_time = begin_time
                        vehicle.end_time = end_time
                        vehicle.is_active = True
                        vehicle.save(update_fields=['start_time', 'end_time', 'is_active'])
                        updated_vehicles += 1

                if sync_camera and cam:
                    result = cam.add_to_whitelist(
                        plate_no,
                        visitor_name=owner_name or None,
                        expiry_hours=expiry_hours,
                        begin_time=begin_time,
                        end_time=end_time,
                        camera_target='resident',
                    )

                    if result.get('success'):
                        sync_success += 1
                        self.stdout.write(self.style.SUCCESS(f"{plate_no} synced: {result.get('message')}"))
                    else:
                        sync_failed += 1
                        self.stdout.write(self.style.WARNING(f"{plate_no} failed: {result.get('error')}"))

        self.stdout.write(self.style.SUCCESS('Import finished'))
        summary = (
            f'Residents created: {created_residents}, updated: {updated_residents}\n'
            f'Vehicles created: {created_vehicles}, updated: {updated_vehicles}\n'
            f'Skipped rows: {skipped_rows}\n'
            + (f'Sync success: {sync_success}, Sync failed: {sync_failed}' if sync_camera else 'Camera sync skipped')
        )
        self.stdout.write(summary)