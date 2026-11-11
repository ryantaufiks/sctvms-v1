"""
Resident Management Service Layer
Provides reusable business logic for resident management operations.
"""
import csv
import re
from io import StringIO
from datetime import datetime
from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from visitors.hikvision_utils import HikvisionTerminalManager
from visitors.alpr_utils import ALPRCameraManager
from .models import Resident, ResidentVehicle


class ResidentStatisticsService:
    """Service for generating resident statistics."""
    
    @staticmethod
    def get_statistics():
        """Get comprehensive statistics for resident management dashboard."""
        total_residents = Resident.objects.count()
        active_residents = Resident.objects.filter(is_active=True).count()
        inactive_residents = total_residents - active_residents
        
        total_vehicles = ResidentVehicle.objects.count()
        active_vehicles = ResidentVehicle.objects.filter(is_active=True).count()
        synced_vehicles = ResidentVehicle.objects.filter(whitelist_synced=True).count()
        not_synced_vehicles = total_vehicles - synced_vehicles
        
        fr_provisioned = Resident.objects.exclude(
            terminal_user_id__isnull=True
        ).exclude(terminal_user_id='').count()
        
        residents_with_vehicles = Resident.objects.annotate(
            vehicle_count=Count('vehicles')
        ).filter(vehicle_count__gt=0).count()
        
        return {
            'total_residents': total_residents,
            'active_residents': active_residents,
            'inactive_residents': inactive_residents,
            'total_vehicles': total_vehicles,
            'active_vehicles': active_vehicles,
            'synced_vehicles': synced_vehicles,
            'not_synced_vehicles': not_synced_vehicles,
            'fr_provisioned': fr_provisioned,
            'residents_with_vehicles': residents_with_vehicles,
        }


class FRProvisioningService:
    """Service for Face Recognition terminal provisioning."""
    
    def __init__(self):
        self.manager = HikvisionTerminalManager()
    
    def _prepare_datetime(self, dt, default_future_days=365):
        """Prepare datetime for FR terminal (timezone aware)."""
        now = timezone.now()
        if dt:
            if dt.tzinfo is None and settings.USE_TZ:
                aware_dt = timezone.make_aware(dt)
            else:
                aware_dt = dt
            local_dt = timezone.localtime(aware_dt) if settings.USE_TZ else aware_dt
        else:
            local_dt = timezone.localtime(now) if settings.USE_TZ else now
        return local_dt
    
    def provision_resident(self, resident, face_file=None, fr_start=None, fr_end=None):
        """
        Provision or update a resident on the FR terminal.
        
        Returns:
            dict: Result with 'success', 'message', and optionally 'error' keys
        """
        try:
            local_start = self._prepare_datetime(fr_start)
            local_end = self._prepare_datetime(fr_end)
            
            if not fr_end:
                local_end = local_start + timezone.timedelta(days=365)
            if local_end <= local_start:
                local_end = local_start + timezone.timedelta(hours=1)
            
            employee_no = str(resident.id).zfill(6)
            
            created = self.manager.create_user_json_with_rights_and_pin(
                employee_no=employee_no,
                name=resident.full_name,
                start_time=local_start,
                end_time=local_end,
                pin=None,
            )
            
            face_uploaded = False
            if face_file:
                image_bytes = face_file.read()
                face_uploaded = self.manager.upload_face_image(
                    employee_no=employee_no,
                    image_content=image_bytes,
                )
                if face_uploaded:
                    self.manager.enable_face_access(employee_no)
            
            if created:
                resident.terminal_user_id = employee_no
                resident.fr_valid_from = local_start
                resident.fr_valid_until = local_end
                resident.save(update_fields=['terminal_user_id', 'fr_valid_from', 'fr_valid_until'])
                
                if face_file and face_uploaded:
                    return {'success': True, 'message': 'Resident provisioned with face image'}
                elif face_file:
                    return {'success': True, 'message': 'Resident provisioned but face upload failed'}
                else:
                    return {'success': True, 'message': 'Resident provisioned (no face image)'}
            else:
                return {'success': False, 'error': 'Failed to create user on FR terminal'}
                
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def deprovision_resident(self, resident):
        """Remove a resident from the FR terminal."""
        try:
            if resident.terminal_user_id:
                if not self.manager.delete_user(employee_no=resident.terminal_user_id):
                    return {'success': False, 'error': 'Failed to remove resident from FR terminal'}
                resident.terminal_user_id = None
                resident.fr_valid_from = None
                resident.fr_valid_until = None
                resident.save(update_fields=['terminal_user_id', 'fr_valid_from', 'fr_valid_until'])
                return {'success': True, 'message': 'Resident removed from FR terminal'}
            return {'success': True, 'message': 'Resident was not provisioned'}
        except Exception as e:
            return {'success': False, 'error': str(e)}


class VehicleWhitelistService:
    """Service for ALPR camera whitelist management."""
    
    def __init__(self):
        self.manager = ALPRCameraManager()
    
    def whitelist_vehicle(self, vehicle, resident_name):
        """Add or update a vehicle in the ALPR whitelist."""
        try:
            now = timezone.now()
            begin_time = vehicle.start_time or now
            if begin_time > now:
                begin_time = now
            
            end_time = vehicle.end_time or (begin_time + timezone.timedelta(hours=24))
            if end_time <= begin_time:
                end_time = begin_time + timezone.timedelta(hours=1)
            
            expiry_hours = max(1, int((end_time - begin_time).total_seconds() // 3600))
            
            result = self.manager.add_to_whitelist(
                vehicle.plate_number,
                visitor_name=resident_name,
                expiry_hours=expiry_hours,
                begin_time=begin_time,
                end_time=end_time,
                camera_target="resident",
            )
            
            if result.get('success'):
                vehicle.whitelist_synced = True
                vehicle.whitelist_synced_at = now
                vehicle.save(update_fields=['whitelist_synced', 'whitelist_synced_at'])
            
            return result
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def remove_vehicle(self, plate_number):
        """Remove a vehicle from the ALPR whitelist."""
        try:
            result = self.manager.remove_from_whitelist(
                plate_number=plate_number
            )
            return result
        except Exception as e:
            return {'success': False, 'error': str(e)}


class ResidentExportService:
    """Service for exporting resident data."""
    
    @staticmethod
    def export_residents_csv(queryset):
        """Export residents to CSV format."""
        output = StringIO()
        writer = csv.writer(output)
        
        writer.writerow([
            'ID', 'Full Name', 'Tower', 'Level', 'Unit',
            'Phone Number', 'Email', 'Status', 'FR Provisioned',
            'Active Vehicles', 'Created At'
        ])
        
        for resident in queryset:
            writer.writerow([
                resident.id,
                resident.full_name,
                resident.tower or '',
                resident.level or '',
                resident.unit or '',
                resident.phone_number or '',
                resident.email or '',
                'Active' if resident.is_active else 'Inactive',
                'Yes' if resident.terminal_user_id else 'No',
                resident.vehicles.filter(is_active=True).count(),
                resident.created_at.strftime('%Y-%m-%d %H:%M') if resident.created_at else '',
            ])
        
        return output.getvalue()
    
    @staticmethod
    def export_vehicles_csv(queryset):
        """Export vehicles to CSV format."""
        output = StringIO()
        writer = csv.writer(output)
        
        writer.writerow([
            'ID', 'Plate Number', 'Resident Name', 'Tower', 'Level', 'Unit',
            'Status', 'Start Time', 'End Time', 'Created At'
        ])
        
        for vehicle in queryset:
            writer.writerow([
                vehicle.id,
                vehicle.plate_number,
                vehicle.resident.full_name,
                vehicle.resident.tower or '',
                vehicle.resident.level or '',
                vehicle.resident.unit or '',
                'Active' if vehicle.is_active else 'Inactive',
                vehicle.start_time.strftime('%Y-%m-%d %H:%M') if vehicle.start_time else '',
                vehicle.end_time.strftime('%Y-%m-%d %H:%M') if vehicle.end_time else '',
                vehicle.created_at.strftime('%Y-%m-%d %H:%M') if vehicle.created_at else '',
            ])
        
        return output.getvalue()


class ResidentBulkOperationsService:
    """Service for bulk operations on residents."""
    
    @staticmethod
    def bulk_activate(resident_ids):
        """Activate multiple residents."""
        count = Resident.objects.filter(id__in=resident_ids).update(is_active=True)
        return {'success': True, 'count': count, 'message': f'{count} residents activated'}
    
    @staticmethod
    def bulk_deactivate(resident_ids):
        """Deactivate multiple residents."""
        count = Resident.objects.filter(id__in=resident_ids).update(is_active=False)
        return {'success': True, 'count': count, 'message': f'{count} residents deactivated'}
    
    @staticmethod
    def bulk_delete(resident_ids):
        """Delete multiple residents."""
        residents = Resident.objects.filter(id__in=resident_ids)
        count = residents.count()
        
        fr_service = FRProvisioningService()
        for resident in residents:
            if resident.terminal_user_id:
                fr_service.deprovision_resident(resident)
        
        residents.delete()
        return {'success': True, 'count': count, 'message': f'{count} residents deleted'}


class BulkVehicleUploadService:
    """Service for bulk uploading resident vehicles from CSV."""
    
    REQUIRED_HEADERS = ['Plate No.', 'Owner Name']
    OPTIONAL_HEADERS = ['Phone', 'Email', 'Tower', 'Level', 'Unit', 'Start Time', 'End Time', 'Remarks']
    
    @staticmethod
    def generate_template_csv():
        """Generate a CSV template for bulk upload."""
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'Plate No.', 'Owner Name', 'Phone', 'Email', 
            'Tower', 'Level', 'Unit', 'Start Time', 'End Time', 'Remarks'
        ])
        writer.writerow([
            'SBC2800E', 'NG HOCK SENG', '81234567', 'example@email.com',
            'A', '12', '01', '2024-10-01', '2029-10-01', 'Owner - 2 cars'
        ])
        writer.writerow([
            'GBF1268H', 'LEE BYOUNG SU', '91234567', '',
            'B', '05', '02', '2024-10-01', '2029-10-01', 'Tenant'
        ])
        return output.getvalue()
    
    @staticmethod
    def normalize_plate(plate):
        """Normalize plate number: uppercase, remove extra spaces."""
        if not plate:
            return ''
        return re.sub(r'\s+', ' ', plate.strip().upper())
    
    @staticmethod
    def parse_date(date_str):
        """Parse date string in various formats."""
        if not date_str or not date_str.strip():
            return None
        date_str = date_str.strip()
        formats = [
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M',
            '%Y-%m-%d',
            '%d/%m/%Y %H:%M:%S',
            '%d/%m/%Y %H:%M',
            '%d/%m/%Y',
            '%d-%m-%Y',
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                if settings.USE_TZ:
                    return timezone.make_aware(dt)
                return dt
            except ValueError:
                continue
        return None
    
    def parse_csv(self, csv_file):
        """
        Parse CSV file and return parsed rows with validation.
        Returns: dict with 'rows', 'errors', 'headers'
        """
        try:
            content = csv_file.read()
            if isinstance(content, bytes):
                content = content.decode('utf-8-sig')
        except Exception as e:
            return {'success': False, 'error': f'Failed to read file: {str(e)}'}
        
        reader = csv.DictReader(StringIO(content))
        headers = reader.fieldnames or []
        
        missing_required = [h for h in self.REQUIRED_HEADERS if h not in headers]
        if missing_required:
            return {
                'success': False, 
                'error': f'Missing required columns: {", ".join(missing_required)}'
            }
        
        rows = []
        errors = []
        row_num = 1
        
        for row in reader:
            row_num += 1
            row_errors = []
            
            plate = self.normalize_plate(row.get('Plate No.', ''))
            owner_name = (row.get('Owner Name') or '').strip()
            
            if not plate:
                row_errors.append('Plate No. is required')
            if not owner_name:
                row_errors.append('Owner Name is required')
            
            start_time = self.parse_date(row.get('Start Time', ''))
            end_time = self.parse_date(row.get('End Time', ''))
            
            if row.get('Start Time') and not start_time:
                row_errors.append(f'Invalid Start Time format: {row.get("Start Time")}')
            if row.get('End Time') and not end_time:
                row_errors.append(f'Invalid End Time format: {row.get("End Time")}')
            
            if start_time and end_time and end_time <= start_time:
                row_errors.append('End Time must be after Start Time')
            
            parsed_row = {
                'row_num': row_num,
                'plate': plate,
                'owner_name': owner_name,
                'phone': (row.get('Phone') or '').strip(),
                'email': (row.get('Email') or '').strip(),
                'tower': (row.get('Tower') or '').strip(),
                'level': (row.get('Level') or '').strip(),
                'unit': (row.get('Unit') or '').strip(),
                'start_time': start_time,
                'end_time': end_time,
                'remarks': (row.get('Remarks') or '').strip(),
                'errors': row_errors,
                'status': 'error' if row_errors else 'pending'
            }
            
            if row_errors:
                errors.append({'row': row_num, 'errors': row_errors})
            
            rows.append(parsed_row)
        
        return {
            'success': True,
            'rows': rows,
            'errors': errors,
            'headers': headers,
            'total': len(rows),
            'valid': len([r for r in rows if r['status'] == 'pending']),
            'invalid': len([r for r in rows if r['status'] == 'error'])
        }
    
    def preview_import(self, rows):
        """
        Analyze rows and determine action (create/update) for each.
        Returns rows with 'action' field: 'create_resident', 'update_resident', 'add_vehicle', 'update_vehicle'
        """
        for row in rows:
            if row['status'] == 'error':
                continue
            
            plate = row['plate']
            owner_name = row['owner_name']
            tower = row['tower']
            level = row['level']
            unit = row['unit']
            
            existing_vehicle = ResidentVehicle.objects.filter(
                plate_number__iexact=plate
            ).select_related('resident').first()
            
            if existing_vehicle:
                row['action'] = 'update_vehicle'
                row['existing_resident_id'] = existing_vehicle.resident.id
                row['existing_vehicle_id'] = existing_vehicle.id
                row['existing_resident_name'] = existing_vehicle.resident.full_name
            else:
                existing_resident = None
                if tower and level and unit:
                    existing_resident = Resident.objects.filter(
                        full_name__iexact=owner_name,
                        tower__iexact=tower,
                        level__iexact=level,
                        unit__iexact=unit
                    ).first()
                
                if not existing_resident:
                    existing_resident = Resident.objects.filter(
                        full_name__iexact=owner_name
                    ).first()
                
                if existing_resident:
                    row['action'] = 'add_vehicle'
                    row['existing_resident_id'] = existing_resident.id
                    row['existing_resident_name'] = existing_resident.full_name
                else:
                    row['action'] = 'create_resident'
        
        return rows
    
    def execute_import(self, rows, user=None, sync_to_camera=True):
        """
        Execute the import: create/update residents and vehicles.
        Skip rows with errors. Returns summary.
        Auto-assigns plate_order for new vehicles.
        """
        results = {
            'residents_created': 0,
            'residents_updated': 0,
            'vehicles_created': 0,
            'vehicles_updated': 0,
            'skipped': 0,
            'sync_success': 0,
            'sync_failed': 0,
            'row_results': []
        }
        
        whitelist_service = VehicleWhitelistService() if sync_to_camera else None
        
        # Pre-compute plate_order assignments for bulk upload
        # Track used plate_orders per resident (including existing + new from this batch)
        resident_plate_orders = {}  # resident_id -> set of used plate_orders
        
        # First pass: collect existing plate_orders and plan assignments
        for row in rows:
            if row['status'] == 'error':
                continue
            action = row.get('action', 'create_resident')
            
            if action == 'create_resident':
                # New resident - use a temporary key based on owner_name + address
                temp_key = f"new_{row['owner_name']}_{row['tower']}_{row['level']}_{row['unit']}"
                if temp_key not in resident_plate_orders:
                    resident_plate_orders[temp_key] = set()
                # Find next available plate_order for this new resident
                for order in [1, 2, 3, 4]:
                    if order not in resident_plate_orders[temp_key]:
                        row['_assigned_plate_order'] = order
                        resident_plate_orders[temp_key].add(order)
                        break
                        
            elif action == 'add_vehicle':
                resident_id = row.get('existing_resident_id')
                if resident_id:
                    if resident_id not in resident_plate_orders:
                        # Get existing plate_orders from database
                        resident = Resident.objects.get(id=resident_id)
                        existing_orders = set(
                            resident.vehicles.exclude(plate_order__isnull=True)
                            .values_list('plate_order', flat=True)
                        )
                        resident_plate_orders[resident_id] = existing_orders
                    # Find next available plate_order
                    for order in [1, 2, 3, 4]:
                        if order not in resident_plate_orders[resident_id]:
                            row['_assigned_plate_order'] = order
                            resident_plate_orders[resident_id].add(order)
                            break
        
        for row in rows:
            if row['status'] == 'error':
                results['skipped'] += 1
                results['row_results'].append({
                    'row_num': row['row_num'],
                    'status': 'skipped',
                    'message': 'Validation errors'
                })
                continue
            
            try:
                with transaction.atomic():
                    action = row.get('action', 'create_resident')
                    
                    if action == 'create_resident':
                        resident = Resident.objects.create(
                            full_name=row['owner_name'],
                            phone_number=row['phone'],
                            email=row['email'],
                            tower=row['tower'],
                            level=row['level'],
                            unit=row['unit'],
                            is_active=True
                        )
                        results['residents_created'] += 1
                        
                        now = timezone.now()
                        vehicle = ResidentVehicle.objects.create(
                            resident=resident,
                            plate_number=row['plate'],
                            plate_order=row.get('_assigned_plate_order'),
                            start_time=row['start_time'] or now,
                            end_time=row['end_time'],
                            remarks=row['remarks'],
                            is_active=True,
                            created_by=user
                        )
                        results['vehicles_created'] += 1
                        
                    elif action == 'add_vehicle':
                        resident = Resident.objects.get(id=row['existing_resident_id'])
                        if row['phone'] and not resident.phone_number:
                            resident.phone_number = row['phone']
                        if row['email'] and not resident.email:
                            resident.email = row['email']
                        if row['tower'] and not resident.tower:
                            resident.tower = row['tower']
                        if row['level'] and not resident.level:
                            resident.level = row['level']
                        if row['unit'] and not resident.unit:
                            resident.unit = row['unit']
                        resident.save()
                        
                        now = timezone.now()
                        vehicle = ResidentVehicle.objects.create(
                            resident=resident,
                            plate_number=row['plate'],
                            plate_order=row.get('_assigned_plate_order'),
                            start_time=row['start_time'] or now,
                            end_time=row['end_time'],
                            remarks=row['remarks'],
                            is_active=True,
                            created_by=user
                        )
                        results['vehicles_created'] += 1
                        
                    elif action == 'update_vehicle':
                        vehicle = ResidentVehicle.objects.get(id=row['existing_vehicle_id'])
                        resident = vehicle.resident
                        
                        if row['start_time']:
                            vehicle.start_time = row['start_time']
                        if row['end_time']:
                            vehicle.end_time = row['end_time']
                        if row['remarks']:
                            vehicle.remarks = row['remarks']
                        vehicle.is_active = True
                        vehicle.save()
                        results['vehicles_updated'] += 1
                        
                        if row['phone'] and not resident.phone_number:
                            resident.phone_number = row['phone']
                        if row['email'] and not resident.email:
                            resident.email = row['email']
                        if row['tower'] and not resident.tower:
                            resident.tower = row['tower']
                        if row['level'] and not resident.level:
                            resident.level = row['level']
                        if row['unit'] and not resident.unit:
                            resident.unit = row['unit']
                        resident.save()
                    
                    if sync_to_camera and whitelist_service:
                        try:
                            sync_result = whitelist_service.whitelist_vehicle(vehicle, resident.full_name)
                            if sync_result.get('success'):
                                results['sync_success'] += 1
                            else:
                                results['sync_failed'] += 1
                        except Exception:
                            results['sync_failed'] += 1
                    
                    results['row_results'].append({
                        'row_num': row['row_num'],
                        'status': 'success',
                        'action': action,
                        'plate': row['plate'],
                        'resident': resident.full_name
                    })
                    
            except Exception as e:
                results['skipped'] += 1
                results['row_results'].append({
                    'row_num': row['row_num'],
                    'status': 'error',
                    'message': str(e)
                })
        
        return results
