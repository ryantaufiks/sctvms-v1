import json
import logging
import re
from io import BytesIO

from datetime import datetime
from django.conf import settings

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


def natural_sort_key(s):
    """Natural sort key for sorting strings with numbers correctly."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(s))]
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from site_settings.models import AddressConfiguration
from visitors.alpr_utils import ALPRCameraManager
from visitors.hikvision_utils import HikvisionTerminalManager

from .forms import ResidentForm, ResidentVehicleForm
from .models import Resident, ResidentVehicle, ResidentVehicleLog

logger = logging.getLogger(__name__)
from .services import (
    BulkVehicleUploadService,
    FRProvisioningService,
    ResidentBulkOperationsService,
    ResidentExportService,
    ResidentStatisticsService,
    VehicleWhitelistService,
)


def serialize_rows_for_session(rows):
    """Convert datetime objects to ISO strings for JSON session storage."""
    serialized = []
    for row in rows:
        new_row = row.copy()
        if new_row.get('start_time') and hasattr(new_row['start_time'], 'isoformat'):
            new_row['start_time'] = new_row['start_time'].isoformat()
        if new_row.get('end_time') and hasattr(new_row['end_time'], 'isoformat'):
            new_row['end_time'] = new_row['end_time'].isoformat()
        serialized.append(new_row)
    return serialized


def deserialize_rows_from_session(rows):
    """Convert ISO strings back to datetime objects from session."""
    from django.utils import timezone as tz
    deserialized = []
    for row in rows:
        new_row = row.copy()
        if new_row.get('start_time') and isinstance(new_row['start_time'], str):
            try:
                dt = datetime.fromisoformat(new_row['start_time'])
                if settings.USE_TZ and dt.tzinfo is None:
                    dt = tz.make_aware(dt)
                new_row['start_time'] = dt
            except ValueError:
                pass
        if new_row.get('end_time') and isinstance(new_row['end_time'], str):
            try:
                dt = datetime.fromisoformat(new_row['end_time'])
                if settings.USE_TZ and dt.tzinfo is None:
                    dt = tz.make_aware(dt)
                new_row['end_time'] = dt
            except ValueError:
                pass
        deserialized.append(new_row)
    return deserialized


def can_manage_residents(user):
    """Check if user has permission to manage residents."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    # Check role via profile (not user.role directly)
    if hasattr(user, 'profile') and hasattr(user.profile, 'role'):
        role = str(user.profile.role).strip().lower().replace(' ', '_')
        if role in ['admin', 'superadmin', 'super_admin', 'manager', 'management']:
            return True
    return user.has_perm('residents.change_resident')


@login_required
@user_passes_test(can_manage_residents, login_url='/accounts/login/')
def management(request):
    """
    Resident Management page with tabs:
    - Resident tab: consolidated resident report + Add Resident modal
    - Vehicle tab: consolidated vehicle report + Add Vehicle modal
    """
    # Feature flag guard: block access when Resident Management is disabled
    from site_settings.models import SiteConfiguration
    config = SiteConfiguration.objects.first()
    if config and not getattr(config, 'enable_resident_management', False):
        messages.error(request, 'Resident Management feature is disabled by administrator.')
        return redirect('site_settings:settings_dashboard')

    # Active tab via query param
    active_tab = request.GET.get("tab", "resident")

    # Filters (shared but applied differently per tab)
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status")
    tower = request.GET.get("tower")
    level = request.GET.get("level")
    unit = request.GET.get("unit")

    # --- RESIDENT TAB LOGIC ---
    # Note: vehicles_count is a @property on Resident model, no need to annotate
    residents = Resident.objects.prefetch_related('vehicles').order_by("full_name")
    
    if q:
        residents = residents.filter(
            Q(full_name__icontains=q) |
            Q(phone_number__icontains=q) |
            Q(email__icontains=q) |
            Q(vehicles__plate_number__icontains=q)
        ).distinct()
    if status == "active":
        residents = residents.filter(is_active=True)
    elif status == "inactive":
        residents = residents.filter(is_active=False)
    if tower:
        residents = residents.filter(tower=tower)
    if level:
        residents = residents.filter(level=level)
    if unit:
        residents = residents.filter(unit=unit)
    
    statistics = ResidentStatisticsService.get_statistics()

    # Resident Pagination
    rsize_raw = request.GET.get("rsize") or "10"
    try:
        rsize = int(rsize_raw)
    except ValueError:
        rsize = 10
    if rsize not in (10, 25, 50, 100):
        rsize = 10

    rpage_raw = request.GET.get("rpage") or "1"
    try:
        rpage = int(rpage_raw)
        if rpage < 1:
            rpage = 1
    except ValueError:
        rpage = 1

    resident_paginator = Paginator(residents, rsize)
    residents_page = resident_paginator.get_page(rpage)

    # --- VEHICLE TAB LOGIC ---
    vehicle_rows = []
    vehicles_page = None

    # All residents (for dropdown in Add Vehicle modal)
    all_residents_for_dropdown = Resident.objects.all().order_by("full_name")

    if active_tab == "vehicle":
        # Vehicle Filters
        vq = q
        vstatus = status
        vtower = tower
        vlevel = level
        vunit = unit

        # Filter residents who have vehicles associated
        # We filter residents, not vehicles directly, because the view groups by resident
        vehicle_residents_qs = Resident.objects.filter(vehicles__isnull=False)

        if vq:
            vehicle_residents_qs = vehicle_residents_qs.filter(
                Q(full_name__icontains=vq) | Q(vehicles__plate_number__icontains=vq)
            )
        if vstatus == "active":
            vehicle_residents_qs = vehicle_residents_qs.filter(vehicles__is_active=True)
        elif vstatus == "inactive":
            vehicle_residents_qs = vehicle_residents_qs.filter(
                vehicles__is_active=False
            )
        if vtower:
            vehicle_residents_qs = vehicle_residents_qs.filter(tower=vtower)
        if vlevel:
            vehicle_residents_qs = vehicle_residents_qs.filter(level=vlevel)
        if vunit:
            vehicle_residents_qs = vehicle_residents_qs.filter(unit=vunit)

        # Prefetch vehicles to optimize queries inside the loop
        vehicle_residents_qs = (
            vehicle_residents_qs.prefetch_related(
                Prefetch(
                    "vehicles",
                    queryset=ResidentVehicle.objects.order_by(
                        "-is_active", "-created_at"
                    ),
                )
            )
            .distinct()
            .order_by("full_name")
        )

        # Build vehicle_rows from the filtered residents
        for r in vehicle_residents_qs:
            slots = {1: None, 2: None, 3: None, 4: None}

            # Fill slots with vehicles that have explicit plate_order
            ordered_vehicles = [
                v for v in r.vehicles.all() if v.plate_order is not None
            ]
            for v in ordered_vehicles:
                idx = int(v.plate_order)
                if 1 <= idx <= 4 and slots[idx] is None:
                    slots[idx] = v

            # Fill remaining slots with vehicles that don't have plate_order
            unordered_vehicles = [v for v in r.vehicles.all() if v.plate_order is None]
            for v in unordered_vehicles:
                for i in range(1, 5):
                    if slots[i] is None:
                        slots[i] = v
                        break

            plates_list = [slots[1], slots[2], slots[3], slots[4]]
            has_active = any(v.is_active for v in plates_list if v)

            vehicle_rows.append(
                {
                    "resident": r,
                    "plates": plates_list,
                    "has_active": has_active,
                }
            )

        # Vehicle Pagination (paginate the constructed list of rows)
        vsize_raw = request.GET.get("vsize") or "10"
        try:
            vsize = int(vsize_raw)
        except ValueError:
            vsize = 10
        if vsize not in (10, 25, 50, 100):
            vsize = 10

        vpage_raw = request.GET.get("vpage") or "1"
        try:
            vpage = int(vpage_raw)
            if vpage < 1:
                vpage = 1
        except ValueError:
            vpage = 1

        vehicle_paginator = Paginator(vehicle_rows, vsize)
        vehicles_page = vehicle_paginator.get_page(vpage)

    # --- POST HANDLING ---

    # Add Resident
    if request.method == "POST" and request.POST.get("action") == "add_resident":
        form = ResidentForm(request.POST, request.FILES)
        if form.is_valid():
            resident = form.save()

            # Optional: Provision to FR terminal if face image provided
            face_file = form.cleaned_data.get("face_image")
            fr_start = form.cleaned_data.get("fr_start_time")
            fr_end = form.cleaned_data.get("fr_end_time")

            if face_file:
                try:
                    now = timezone.now()
                    if fr_start:
                        aware_start = (
                            timezone.make_aware(fr_start)
                            if fr_start.tzinfo is None and settings.USE_TZ
                            else fr_start
                        )
                        local_start = (
                            timezone.localtime(aware_start)
                            if settings.USE_TZ
                            else aware_start
                        )
                    else:
                        local_start = (
                            timezone.localtime(now) if settings.USE_TZ else now
                        )

                    if fr_end:
                        aware_end = (
                            timezone.make_aware(fr_end)
                            if fr_end.tzinfo is None and settings.USE_TZ
                            else fr_end
                        )
                        local_end = (
                            timezone.localtime(aware_end)
                            if settings.USE_TZ
                            else aware_end
                        )
                    else:
                        local_end = local_start + timezone.timedelta(days=365)
                    if local_end <= local_start:
                        local_end = local_start + timezone.timedelta(hours=1)

                    employee_no = str(resident.id).zfill(6)
                    manager = HikvisionTerminalManager()
                    created = manager.create_user_json_with_rights_and_pin(
                        employee_no=employee_no,
                        name=resident.full_name,
                        start_time=local_start,
                        end_time=local_end,
                        pin=None,
                    )
                    image_bytes = face_file.read()
                    uploaded = manager.upload_face_image(
                        employee_no=employee_no, image_content=image_bytes
                    )
                    try:
                        manager.enable_face_access(employee_no)
                    except Exception:
                        pass
                    if created and uploaded:
                        resident.terminal_user_id = employee_no
                        resident.fr_valid_from = local_start
                        resident.fr_valid_until = local_end
                        resident.save(
                            update_fields=[
                                "terminal_user_id",
                                "fr_valid_from",
                                "fr_valid_until",
                            ]
                        )
                        messages.success(
                            request,
                            f"Resident '{resident.full_name}' added and face provisioned to FR terminal.",
                        )
                    else:
                        messages.warning(
                            request,
                            f"Resident '{resident.full_name}' added, but FR provisioning failed.",
                        )
                except Exception as e:
                    messages.warning(request, f"Face provisioning error: {e}")
            else:
                messages.success(
                    request, f"Resident '{resident.full_name}' has been added."
                )

            return redirect(
                f"{reverse('residents:management')}?tab=resident&q={q}&status={status}&tower={tower}&level={level}&unit={unit}"
            )
        else:
            messages.error(request, "Failed to add resident. Please check your input.")

    # Edit Resident
    if request.method == "POST" and request.POST.get("action") == "edit_resident":
        resident_id = request.POST.get("resident_id")
        resident = get_object_or_404(Resident, id=resident_id)
        form = ResidentForm(request.POST, request.FILES, instance=resident)
        if form.is_valid():
            resident = form.save()

            face_file = form.cleaned_data.get("face_image")
            fr_start = form.cleaned_data.get("fr_start_time")
            fr_end = form.cleaned_data.get("fr_end_time")

            try:
                now = timezone.now()
                if fr_start:
                    aware_start = (
                        timezone.make_aware(fr_start)
                        if fr_start.tzinfo is None and settings.USE_TZ
                        else fr_start
                    )
                    local_start = (
                        timezone.localtime(aware_start)
                        if settings.USE_TZ
                        else aware_start
                    )
                else:
                    local_start = timezone.localtime(now) if settings.USE_TZ else now

                if fr_end:
                    aware_end = (
                        timezone.make_aware(fr_end)
                        if fr_end.tzinfo is None and settings.USE_TZ
                        else fr_end
                    )
                    local_end = (
                        timezone.localtime(aware_end) if settings.USE_TZ else aware_end
                    )
                else:
                    local_end = local_start + timezone.timedelta(days=365)
                if local_end <= local_start:
                    local_end = local_start + timezone.timedelta(hours=1)

                employee_no = str(resident.id).zfill(6)
                manager = HikvisionTerminalManager()
                manager.create_user_json_with_rights_and_pin(
                    employee_no=employee_no,
                    name=resident.full_name,
                    start_time=local_start,
                    end_time=local_end,
                    pin=None,
                )

                if face_file:
                    image_bytes = face_file.read()
                    uploaded = manager.upload_face_image(
                        employee_no=employee_no, image_content=image_bytes
                    )
                    try:
                        manager.enable_face_access(employee_no)
                    except Exception:
                        pass
                    if uploaded:
                        resident.terminal_user_id = employee_no
                        messages.success(
                            request, "Face image uploaded and FR provisioning updated."
                        )

                resident.fr_valid_from = local_start
                resident.fr_valid_until = local_end
                resident.save(
                    update_fields=[
                        "fr_valid_from",
                        "fr_valid_until",
                        "terminal_user_id",
                    ]
                )
            except Exception as e:
                messages.warning(
                    request, f"Update succeeded, but FR provisioning error: {e}"
                )

            messages.success(
                request, f"Resident '{resident.full_name}' has been updated."
            )
            return redirect(
                f"{reverse('residents:management')}?tab=resident&edit_resident_id={resident.id}&q={q}&status={status}&tower={tower}&level={level}&unit={unit}"
            )
        else:
            messages.error(
                request, "Failed to update resident. Please check your input."
            )

    # Delete Resident
    if request.method == "POST" and request.POST.get("action") == "delete_resident":
        resident_id = request.POST.get("resident_id")
        resident = get_object_or_404(Resident, id=resident_id)
        resident.delete()
        messages.success(request, "Resident has been deleted.")
        return redirect(
            f"{reverse('residents:management')}?tab=resident&q={q}&status={status}&tower={tower}&level={level}&unit={unit}"
        )

    # Add Vehicle
    if request.method == "POST" and request.POST.get("action") == "add_vehicle":
        resident_id = request.POST.get("resident_id")
        resident = get_object_or_404(Resident, id=resident_id)

        if resident.vehicles.filter(is_active=True).count() >= 5:
            messages.error(
                request,
                f"Resident '{resident.full_name}' already has 5 active vehicles.",
            )
        else:
            form = ResidentVehicleForm(request.POST)
            if form.is_valid():
                vehicle = form.save(commit=False)
                vehicle.resident = resident
                vehicle.created_by = request.user

                # Auto-assign plate_order if not provided
                if not vehicle.plate_order:
                    next_order = resident.get_next_plate_order()
                    if next_order:
                        vehicle.plate_order = next_order

                # Validate plate order uniqueness (if user explicitly set it)
                if vehicle.plate_order:
                    exists = resident.vehicles.filter(
                        plate_order=vehicle.plate_order
                    ).exists()
                    if exists:
                        messages.error(
                            request,
                            f"Urutan plat nomor {vehicle.plate_order} sudah dipakai untuk resident ini.",
                        )
                        # Redirect back to the vehicle tab preserving filters
                        return redirect(
                            f"{reverse('residents:management')}?tab=vehicle&q={q}&status={status}&tower={tower}&level={level}&unit={unit}"
                        )

                vehicle.save()

                # Auto-whitelist logic
                now = timezone.now()
                begin_time = vehicle.start_time or now
                if begin_time > now:
                    begin_time = now

                end_time = vehicle.end_time or (
                    begin_time + timezone.timedelta(hours=24)
                )
                if end_time <= begin_time:
                    end_time = begin_time + timezone.timedelta(hours=1)

                expiry_hours = max(
                    1, int((end_time - begin_time).total_seconds() // 3600)
                )

                try:
                    manager = ALPRCameraManager()
                    result = manager.add_to_whitelist(
                        vehicle.plate_number,
                        visitor_name=resident.full_name,
                        expiry_hours=expiry_hours,
                        begin_time=begin_time,
                        end_time=end_time,
                        camera_target="resident",
                    )
                    if result.get("success"):
                        messages.success(
                            request,
                            f"Vehicle {vehicle.plate_number} whitelisted: {result.get('message')}",
                        )
                    else:
                        messages.warning(
                            request,
                            f"Vehicle {vehicle.plate_number} failed to whitelist: {result.get('error')}",
                        )
                except Exception as e:
                    messages.warning(request, f"ALPR integration error: {e}")

                return redirect(
                    f"{reverse('residents:management')}?tab=vehicle&q={q}&status={status}&tower={tower}&level={level}&unit={unit}"
                )
            else:
                messages.error(
                    request, "Failed to add vehicle. Please check your input."
                )

    # Edit Vehicle
    if request.method == "POST" and request.POST.get("action") == "edit_vehicle":
        vehicle_id = request.POST.get("vehicle_id")
        vehicle = get_object_or_404(ResidentVehicle, id=vehicle_id)
        old_plate_number = vehicle.plate_number  # Save old plate before update
        form = ResidentVehicleForm(request.POST, instance=vehicle)
        if form.is_valid():
            updated = form.save(commit=False)
            # Validate plate order uniqueness
            if updated.plate_order:
                dup = (
                    updated.resident.vehicles.filter(plate_order=updated.plate_order)
                    .exclude(id=updated.id)
                    .exists()
                )
                if dup:
                    messages.error(
                        request,
                        f"Urutan plat nomor {updated.plate_order} sudah dipakai untuk resident ini.",
                    )
                    return redirect(
                        f"{reverse('residents:management')}?tab=vehicle&edit_vehicle_id={updated.id}&q={q}&status={status}&tower={tower}&level={level}&unit={unit}"
                    )
            updated.save()

            # Sinkronisasi ke kamera ALPR
            now = timezone.now()
            begin_time = updated.start_time or now
            if begin_time > now:
                begin_time = now
            end_time = updated.end_time or (begin_time + timezone.timedelta(hours=24))
            if end_time <= begin_time:
                end_time = begin_time + timezone.timedelta(hours=1)
            expiry_hours = max(1, int((end_time - begin_time).total_seconds() // 3600))

            try:
                manager = ALPRCameraManager()
                
                # If plate number changed, remove old plate first
                new_plate_normalized = updated.plate_number.replace(' ', '').upper()
                old_plate_normalized = old_plate_number.replace(' ', '').upper()
                
                if old_plate_normalized != new_plate_normalized:
                    # Remove old plate from camera
                    remove_result = manager.remove_from_whitelist(
                        old_plate_number,
                        camera_target="resident",
                    )
                    if remove_result.get("success"):
                        messages.info(
                            request,
                            f"Old plate '{old_plate_number}' removed from camera.",
                        )
                
                # Add/update new plate
                result = manager.add_to_whitelist(
                    updated.plate_number,
                    visitor_name=updated.resident.full_name,
                    expiry_hours=expiry_hours,
                    begin_time=begin_time,
                    end_time=end_time,
                    camera_target="resident",
                )
                if result.get("success"):
                    messages.success(
                        request,
                        f"Vehicle '{updated.plate_number}' updated in camera: {result.get('message')}",
                    )
                else:
                    messages.warning(
                        request,
                        f"Vehicle '{updated.plate_number}' camera update failed: {result.get('error')}",
                    )
            except Exception as e:
                messages.warning(request, f"ALPR camera sync error: {e}")

            messages.success(
                request, f"Vehicle '{vehicle.plate_number}' has been updated."
            )
            return redirect(f"{reverse('residents:management')}?tab=vehicle")
        else:
            messages.error(
                request, "Failed to update vehicle. Please check your input."
            )

    # Delete Vehicle
    if request.method == "POST" and request.POST.get("action") == "delete_vehicle":
        vehicle_id = request.POST.get("vehicle_id")
        vehicle = get_object_or_404(ResidentVehicle, id=vehicle_id)

        # Remove from ALPR camera before deleting from database
        try:
            manager = ALPRCameraManager()
            result = manager.remove_from_whitelist(
                plate_number=vehicle.plate_number,
                camera_target="resident",
            )
            if result.get("success"):
                messages.success(
                    request,
                    f"Vehicle '{vehicle.plate_number}' removed from camera: {result.get('message')}",
                )
            else:
                messages.warning(
                    request,
                    f"Vehicle '{vehicle.plate_number}' camera removal failed: {result.get('error')}",
                )
        except Exception as e:
            messages.warning(request, f"ALPR camera sync error: {e}")

        # Delete from database
        vehicle.delete()
        messages.success(request, "Vehicle has been deleted.")
        return redirect(
            f"{reverse('residents:management')}?tab=vehicle&q={q}&status={status}&tower={tower}&level={level}&unit={unit}"
        )

    # Address configuration with natural sorting for better UX
    address_config = AddressConfiguration.objects.first()
    if address_config:
        if address_config.tower_options:
            address_config.tower_options = sorted(address_config.tower_options, key=natural_sort_key)
        if address_config.level_options:
            address_config.level_options = sorted(address_config.level_options, key=natural_sort_key)
        if address_config.unit_options:
            address_config.unit_options = sorted(address_config.unit_options, key=natural_sort_key)

    # Preload forms for edit modals
    edit_resident_id = request.GET.get("edit_resident_id")
    edit_vehicle_id = request.GET.get("edit_vehicle_id")
    edit_resident_form = None
    edit_vehicle_form = None

    if edit_resident_id:
        try:
            edit_resident_form = ResidentForm(
                instance=Resident.objects.get(id=edit_resident_id)
            )
        except Resident.DoesNotExist:
            pass

    if edit_vehicle_id:
        try:
            edit_vehicle_form = ResidentVehicleForm(
                instance=ResidentVehicle.objects.get(id=edit_vehicle_id)
            )
        except ResidentVehicle.DoesNotExist:
            pass

    # Context Data
    context = {
        "active_tab": active_tab,
        "residents": all_residents_for_dropdown,
        "residents_page": residents_page,
        "vehicle_rows": vehicle_rows,
        "vehicles_page": vehicles_page,
        "resident_form": ResidentForm(),
        "vehicle_form": ResidentVehicleForm(),
        "edit_resident_form": edit_resident_form,
        "edit_vehicle_form": edit_vehicle_form,
        "address_config": address_config,
        "statistics": statistics,
        "filters": {
            "q": q,
            "status": status,
            "tower": tower,
            "level": level,
            "unit": unit,
        },
    }

    return render(request, "residents/management.html", context)


@login_required
@user_passes_test(can_manage_residents, login_url='/accounts/login/')
def bulk_operations(request):
    """Handle bulk operations on residents."""
    if request.method != 'POST':
        return redirect('residents:management')
    
    action = request.POST.get('bulk_action')
    resident_ids = request.POST.getlist('resident_ids')
    
    if not resident_ids:
        messages.warning(request, 'No residents selected.')
        return redirect('residents:management')
    
    if action == 'activate':
        result = ResidentBulkOperationsService.bulk_activate(resident_ids)
        messages.success(request, result['message'])
    elif action == 'deactivate':
        result = ResidentBulkOperationsService.bulk_deactivate(resident_ids)
        messages.success(request, result['message'])
    elif action == 'delete':
        result = ResidentBulkOperationsService.bulk_delete(resident_ids)
        messages.success(request, result['message'])
    else:
        messages.error(request, 'Invalid action.')
    
    return redirect('residents:management')


@login_required
@user_passes_test(can_manage_residents, login_url='/accounts/login/')
def export_residents(request):
    """Export residents to CSV."""
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status')
    tower = request.GET.get('tower')
    level = request.GET.get('level')
    unit = request.GET.get('unit')
    
    queryset = Resident.objects.all().order_by('full_name')
    
    if q:
        queryset = queryset.filter(
            Q(full_name__icontains=q) |
            Q(phone_number__icontains=q) |
            Q(email__icontains=q)
        )
    if status == 'active':
        queryset = queryset.filter(is_active=True)
    elif status == 'inactive':
        queryset = queryset.filter(is_active=False)
    if tower:
        queryset = queryset.filter(tower=tower)
    if level:
        queryset = queryset.filter(level=level)
    if unit:
        queryset = queryset.filter(unit=unit)
    
    csv_content = ResidentExportService.export_residents_csv(queryset)
    
    response = HttpResponse(csv_content, content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="residents_export.csv"'
    return response


@login_required
@user_passes_test(can_manage_residents, login_url='/accounts/login/')
def export_vehicles(request):
    """Export vehicles to CSV."""
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status')
    tower = request.GET.get('tower')
    level = request.GET.get('level')
    unit = request.GET.get('unit')
    
    queryset = ResidentVehicle.objects.select_related('resident').order_by('resident__full_name')
    
    if q:
        queryset = queryset.filter(
            Q(plate_number__icontains=q) |
            Q(resident__full_name__icontains=q)
        )
    if status == 'active':
        queryset = queryset.filter(is_active=True)
    elif status == 'inactive':
        queryset = queryset.filter(is_active=False)
    if tower:
        queryset = queryset.filter(resident__tower=tower)
    if level:
        queryset = queryset.filter(resident__level=level)
    if unit:
        queryset = queryset.filter(resident__unit=unit)
    
    csv_content = ResidentExportService.export_vehicles_csv(queryset)
    
    response = HttpResponse(csv_content, content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="vehicles_export.csv"'
    return response


@login_required
@user_passes_test(can_manage_residents, login_url='/accounts/login/')
def export_vehicles_pdf(request):
    """Export vehicles to PDF."""
    if not REPORTLAB_AVAILABLE:
        messages.error(request, 'PDF export requires reportlab library. Please install it.')
        return redirect('residents:management')
    
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status')
    tower = request.GET.get('tower')
    level = request.GET.get('level')
    unit = request.GET.get('unit')
    
    queryset = ResidentVehicle.objects.select_related('resident').order_by('resident__full_name')
    
    if q:
        queryset = queryset.filter(
            Q(plate_number__icontains=q) |
            Q(resident__full_name__icontains=q)
        )
    if status == 'active':
        queryset = queryset.filter(is_active=True)
    elif status == 'inactive':
        queryset = queryset.filter(is_active=False)
    if tower:
        queryset = queryset.filter(resident__tower=tower)
    if level:
        queryset = queryset.filter(resident__level=level)
    if unit:
        queryset = queryset.filter(resident__unit=unit)
    
    filename = f'vehicles_report_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        leftMargin=36,
        rightMargin=36,
        topMargin=48,
        bottomMargin=36,
    )
    
    elements = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=20,
        alignment=1,
    )
    elements.append(Paragraph('Vehicle Report', title_style))
    
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.gray,
        alignment=1,
        spaceAfter=20,
    )
    filter_text = []
    if q:
        filter_text.append(f'Search: {q}')
    if status:
        filter_text.append(f'Status: {status}')
    if tower:
        filter_text.append(f'Tower: {tower}')
    if level:
        filter_text.append(f'Level: {level}')
    if unit:
        filter_text.append(f'Unit: {unit}')
    
    subtitle = f'Generated: {timezone.now().strftime("%Y-%m-%d %H:%M")}'
    if filter_text:
        subtitle += f' | Filters: {", ".join(filter_text)}'
    elements.append(Paragraph(subtitle, subtitle_style))
    
    stats_data = [
        ['Total Vehicles', 'Active', 'Inactive'],
        [
            str(queryset.count()),
            str(queryset.filter(is_active=True).count()),
            str(queryset.filter(is_active=False).count()),
        ]
    ]
    stats_table = Table(stats_data, colWidths=[2*inch, 2*inch, 2*inch])
    stats_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3B82F6')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#EFF6FF')),
        ('FONTSIZE', (0, 1), (-1, -1), 12),
        ('TOPPADDING', (0, 1), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 1, colors.white),
    ]))
    elements.append(stats_table)
    elements.append(Spacer(1, 20))
    
    table_data = [['No.', 'Plate Number', 'Resident Name', 'Phone', 'Tower', 'Level', 'Unit', 'Status', 'Remarks']]
    
    for idx, vehicle in enumerate(queryset, 1):
        resident = vehicle.resident
        table_data.append([
            str(idx),
            vehicle.plate_number or '',
            resident.full_name if resident else '',
            resident.phone_number if resident else '',
            resident.tower if resident else '',
            resident.level if resident else '',
            resident.unit if resident else '',
            'Active' if vehicle.is_active else 'Inactive',
            vehicle.remarks or '',
        ])
    
    col_widths = [0.4*inch, 1.2*inch, 1.8*inch, 1.2*inch, 0.8*inch, 0.6*inch, 0.6*inch, 0.7*inch, 1.2*inch]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F2937')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('TOPPADDING', (0, 0), (-1, 0), 10),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('ALIGN', (2, 1), (2, -1), 'LEFT'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9FAFB')]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
    ]))
    
    elements.append(table)
    
    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    response.write(pdf)
    
    return response


@csrf_exempt
@require_POST
def resident_vehicle_log_api(request):
    """
    API endpoint for logging resident vehicle detections from ALPR camera.
    Called by Dahua listener service when a resident plate is detected.
    
    Expects JSON body with:
    - plate_number (required)
    - direction: 'in' or 'out' (default: 'in')
    - snapshot_path: path to snapshot image (optional)
    
    Security: Requires X-API-Key header or localhost access.
    """
    try:
        api_key = request.headers.get('X-API-Key', '')
        expected_key = getattr(settings, 'ANPR_LISTENER_API_KEY', '')
        remote_addr = request.META.get('REMOTE_ADDR', '')
        
        is_localhost = remote_addr in ('127.0.0.1', '::1', 'localhost')
        is_valid_key = expected_key and api_key == expected_key
        
        if not is_localhost and not is_valid_key:
            logger.warning(f"Resident log: Unauthorized access attempt from {remote_addr}")
            return JsonResponse({
                'success': False,
                'error': 'Unauthorized: Invalid or missing API key'
            }, status=401)
        
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid JSON body'
            }, status=400)
        
        plate_number = data.get('plate_number', '').strip().upper()
        direction = data.get('direction', 'in').lower()
        snapshot_path = data.get('snapshot_path', '')
        
        if not plate_number:
            return JsonResponse({
                'success': False,
                'error': 'plate_number is required'
            }, status=400)
        
        if direction not in ('in', 'out'):
            direction = 'in'
        
        vehicle = ResidentVehicle.objects.filter(
            plate_number__iexact=plate_number,
            is_active=True
        ).select_related('resident').first()
        
        if not vehicle:
            logger.info(f"Resident log: Plate {plate_number} not found in resident vehicles")
            return JsonResponse({
                'success': False,
                'error': f'Plate {plate_number} not found in active resident vehicles',
                'plate_number': plate_number
            }, status=404)
        
        if not vehicle.resident.is_active:
            logger.info(f"Resident log: Resident {vehicle.resident.full_name} is inactive")
            return JsonResponse({
                'success': False,
                'error': f'Resident {vehicle.resident.full_name} is inactive',
                'plate_number': plate_number
            }, status=400)
        
        log_entry = ResidentVehicleLog.objects.create(
            resident=vehicle.resident,
            vehicle=vehicle,
            plate_number=plate_number,
            direction=direction,
            snapshot_path=snapshot_path
        )
        
        logger.info(f"Resident log: {plate_number} ({direction}) - {vehicle.resident.full_name}")
        
        return JsonResponse({
            'success': True,
            'message': f'Logged {direction} for {vehicle.resident.full_name}',
            'log_id': log_entry.id,
            'resident': {
                'id': vehicle.resident.id,
                'name': vehicle.resident.full_name,
                'unit': log_entry.resident_unit
            },
            'plate_number': plate_number,
            'direction': direction,
            'detected_at': log_entry.detected_at.isoformat()
        })
        
    except Exception as e:
        logger.exception(f"Resident log API error: {e}")
        return JsonResponse({
            'success': False,
            'error': f'Server error: {str(e)}'
        }, status=500)


def get_recent_resident_logs(request):
    """
    API endpoint to get recent resident vehicle logs for dashboard.
    Returns the last N logs (default 20).
    """
    limit = int(request.GET.get('limit', 20))
    limit = min(limit, 100)
    
    logs = ResidentVehicleLog.objects.select_related(
        'resident', 'vehicle'
    ).order_by('-detected_at')[:limit]
    
    data = []
    for log in logs:
        data.append({
            'id': log.id,
            'resident_name': log.resident.full_name,
            'unit': log.resident_unit,
            'plate_number': log.plate_number,
            'direction': log.direction,
            'detected_at': log.detected_at.isoformat(),
            'detected_at_display': log.detected_at.strftime('%H:%M:%S'),
            'detected_date': log.detected_at.strftime('%Y-%m-%d'),
        })
    
    return JsonResponse({
        'success': True,
        'logs': data,
        'count': len(data)
    })


@login_required
@user_passes_test(can_manage_residents, login_url='/accounts/login/')
@require_POST
def update_vehicle_remarks(request):
    """
    API endpoint to update vehicle remarks.
    Expects JSON body with vehicle_id and remarks.
    """
    
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON body'
        }, status=400)
    
    vehicle_id = data.get('vehicle_id')
    remarks = data.get('remarks', '').strip()
    
    if not vehicle_id:
        return JsonResponse({
            'success': False,
            'error': 'vehicle_id is required'
        }, status=400)
    
    try:
        vehicle = ResidentVehicle.objects.get(id=vehicle_id)
        vehicle.remarks = remarks
        vehicle.save(update_fields=['remarks', 'updated_at'])
        
        return JsonResponse({
            'success': True,
            'message': 'Remarks updated successfully',
            'vehicle_id': vehicle_id,
            'remarks': remarks
        })
    except ResidentVehicle.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Vehicle not found'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(can_manage_residents, login_url='/accounts/login/')
def bulk_upload_vehicles(request):
    """
    Bulk upload vehicles from CSV file.
    Step 1: Upload CSV -> Parse and Preview
    Step 2: Confirm -> Execute Import
    """
    service = BulkVehicleUploadService()
    
    if request.method == 'POST':
        step = request.POST.get('step', 'upload')
        
        if step == 'upload':
            csv_file = request.FILES.get('csv_file')
            if not csv_file:
                messages.error(request, 'Please select a CSV file to upload.')
                return redirect('residents:bulk_upload')
            
            if not csv_file.name.endswith('.csv'):
                messages.error(request, 'Please upload a valid CSV file.')
                return redirect('residents:bulk_upload')
            
            parse_result = service.parse_csv(csv_file)
            
            if not parse_result.get('success'):
                messages.error(request, parse_result.get('error', 'Failed to parse CSV'))
                return redirect('residents:bulk_upload')
            
            rows = service.preview_import(parse_result['rows'])
            
            request.session['bulk_upload_rows'] = serialize_rows_for_session(rows)
            
            context = {
                'step': 'preview',
                'rows': rows,
                'total': parse_result['total'],
                'valid': parse_result['valid'],
                'invalid': parse_result['invalid'],
                'create_count': len([r for r in rows if r.get('action') == 'create_resident']),
                'add_count': len([r for r in rows if r.get('action') == 'add_vehicle']),
                'update_count': len([r for r in rows if r.get('action') == 'update_vehicle']),
            }
            return render(request, 'residents/bulk_upload.html', context)
        
        elif step == 'confirm':
            rows_raw = request.session.get('bulk_upload_rows', [])
            if not rows_raw:
                messages.error(request, 'No data to import. Please upload a CSV file first.')
                return redirect('residents:bulk_upload')
            
            rows = deserialize_rows_from_session(rows_raw)
            sync_to_camera = request.POST.get('sync_to_camera', 'on') == 'on'
            
            results = service.execute_import(rows, user=request.user, sync_to_camera=sync_to_camera)
            
            del request.session['bulk_upload_rows']
            
            messages.success(
                request, 
                f"Import completed: {results['residents_created']} residents created, "
                f"{results['vehicles_created']} vehicles created, "
                f"{results['vehicles_updated']} vehicles updated. "
                f"Camera sync: {results['sync_success']} success, {results['sync_failed']} failed."
            )
            
            context = {
                'step': 'results',
                'results': results,
            }
            return render(request, 'residents/bulk_upload.html', context)
    
    return render(request, 'residents/bulk_upload.html', {'step': 'upload'})


@login_required
@user_passes_test(can_manage_residents, login_url='/accounts/login/')
def download_bulk_upload_template(request):
    """Download CSV template for bulk upload."""
    csv_content = BulkVehicleUploadService.generate_template_csv()
    
    response = HttpResponse(csv_content, content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="vehicle_upload_template.csv"'
    return response


@login_required
@user_passes_test(can_manage_residents, login_url='/accounts/login/')
@require_POST
def sync_vehicle_to_camera(request):
    """API endpoint to manually sync a vehicle to the ALPR camera."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    
    vehicle_id = data.get('vehicle_id')
    if not vehicle_id:
        return JsonResponse({'success': False, 'error': 'vehicle_id is required'}, status=400)
    
    try:
        vehicle = ResidentVehicle.objects.select_related('resident').get(id=vehicle_id)
    except ResidentVehicle.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Vehicle not found'}, status=404)
    
    service = VehicleWhitelistService()
    result = service.whitelist_vehicle(vehicle, vehicle.resident.full_name)
    
    if result.get('success'):
        return JsonResponse({
            'success': True,
            'message': 'Vehicle synced to camera successfully',
            'synced_at': vehicle.whitelist_synced_at.isoformat() if vehicle.whitelist_synced_at else None
        })
    else:
        return JsonResponse({
            'success': False,
            'error': result.get('error', 'Failed to sync to camera')
        }, status=500)


@login_required
@user_passes_test(can_manage_residents, login_url='/accounts/login/')
@require_POST
def sync_all_vehicles_to_camera(request):
    """API endpoint to sync all unsynced vehicles to the ALPR camera.
    
    Uses individual add_to_whitelist calls for reliability (bulk upload API
    may not be supported by all Dahua camera models).
    """
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        data = {}
    
    sync_all = data.get('sync_all', False)
    
    from visitors.alpr_utils import ALPRCameraManager
    from django.utils import timezone
    from datetime import timedelta
    
    if sync_all:
        vehicles = ResidentVehicle.objects.select_related('resident').filter(
            resident__is_active=True
        )
    else:
        vehicles = ResidentVehicle.objects.select_related('resident').filter(
            whitelist_synced=False,
            resident__is_active=True
        )
    
    if not vehicles.exists():
        return JsonResponse({
            'success': True,
            'message': 'No vehicles to sync',
            'synced_count': 0,
            'failed_count': 0
        })
    
    camera_manager = ALPRCameraManager()
    synced_count = 0
    failed_count = 0
    failed_plates = []
    now = timezone.now()
    
    for vehicle in vehicles:
        begin_time = vehicle.start_time or now
        if begin_time > now:
            begin_time = now
        end_time = vehicle.end_time or (begin_time + timedelta(days=365*20))
        if end_time <= begin_time:
            end_time = begin_time + timedelta(days=365*20)
        expiry_hours = max(1, int((end_time - begin_time).total_seconds() // 3600))
        
        result = camera_manager.add_to_whitelist(
            vehicle.plate_number,
            visitor_name=vehicle.resident.full_name if vehicle.resident else '',
            expiry_hours=expiry_hours,
            begin_time=begin_time,
            end_time=end_time,
            camera_target='resident'
        )
        
        if result.get('success'):
            vehicle.whitelist_synced = True
            vehicle.whitelist_synced_at = now
            vehicle.save(update_fields=['whitelist_synced', 'whitelist_synced_at'])
            synced_count += 1
        else:
            failed_count += 1
            failed_plates.append(vehicle.plate_number)
    
    stats = ResidentStatisticsService.get_statistics()
    
    if synced_count > 0:
        return JsonResponse({
            'success': True,
            'message': f'{synced_count} vehicle(s) synced successfully' + (f', {failed_count} failed' if failed_count > 0 else ''),
            'synced_count': synced_count,
            'failed_count': failed_count,
            'failed_plates': failed_plates[:10],
            'stats': {
                'synced_vehicles': stats.get('synced_vehicles', 0),
                'not_synced_vehicles': stats.get('not_synced_vehicles', 0)
            }
        })
    else:
        return JsonResponse({
            'success': False,
            'error': f'All {failed_count} vehicle(s) failed to sync',
            'synced_count': 0,
            'failed_count': failed_count,
            'failed_plates': failed_plates[:10]
        }, status=500)
