from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from accounts.decorators import admin_required
from django.contrib import messages
from django.utils import timezone
from django.conf import settings
from django.core.paginator import Paginator
from .models import Resident, ResidentVehicle
from .forms import ResidentForm, ResidentVehicleForm
from visitors.alpr_utils import ALPRCameraManager
from visitors.hikvision_utils import HikvisionTerminalManager
from site_settings.models import AddressConfiguration, SiteConfiguration


@login_required
@admin_required
def management(request):
    """
    Resident Management page with tabs:
    - Resident tab: consolidated resident report + Add Resident modal
    - Vehicle tab: consolidated vehicle report + Add Vehicle modal
    """
    # Feature flag guard: block access when Resident Management is disabled
    try:
        config = SiteConfiguration.objects.first()
    except Exception:
        config = None
    if config and not getattr(config, 'enable_resident_management', False):
        messages.error(request, 'Resident Management feature is disabled by administrator.')
        return redirect('site_settings:settings_dashboard')
    from django.db.models import Q
    from django.urls import reverse

    # Active tab via query param
    active_tab = request.GET.get('tab', 'resident')

    # Filters for Resident report
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status')  # 'active' or 'inactive' or None
    tower = request.GET.get('tower')
    level = request.GET.get('level')
    unit = request.GET.get('unit')

    residents = Resident.objects.all().order_by('full_name')
    if q:
        residents = residents.filter(full_name__icontains=q)
    if status == 'active':
        residents = residents.filter(is_active=True)
    elif status == 'inactive':
        residents = residents.filter(is_active=False)
    if tower:
        residents = residents.filter(tower=tower)
    if level:
        residents = residents.filter(level=level)
    if unit:
        residents = residents.filter(unit=unit)

    # Pagination for Resident report
    rpage = request.GET.get('rpage', 1)
    resident_paginator = Paginator(residents, 10)
    residents_page = resident_paginator.get_page(rpage)

    # Vehicle report aggregated per resident (Plate No 1/2/3)
    vehicles = ResidentVehicle.objects.select_related('resident').all().order_by('-created_at')
    vehicle_rows = []
    vehicles_page = None
    if active_tab == 'vehicle':
        vq = q
        vstatus = status
        vtower = tower
        vlevel = level
        vunit = unit

        vehicle_residents = Resident.objects.all()
        if vq:
            vehicle_residents = vehicle_residents.filter(
                Q(full_name__icontains=vq) | Q(vehicles__plate_number__icontains=vq)
            )
        if vstatus == 'active':
            vehicle_residents = vehicle_residents.filter(vehicles__is_active=True)
        elif vstatus == 'inactive':
            vehicle_residents = vehicle_residents.filter(vehicles__is_active=False)
        if vtower:
            vehicle_residents = vehicle_residents.filter(tower=vtower)
        if vlevel:
            vehicle_residents = vehicle_residents.filter(level=vlevel)
        if vunit:
            vehicle_residents = vehicle_residents.filter(unit=vunit)

        vehicle_residents = vehicle_residents.distinct().order_by('full_name')

        for r in vehicle_residents:
            top_vehicles = list(r.vehicles.order_by('-is_active', '-created_at')[:3])
            has_active = r.vehicles.filter(is_active=True).exists()
            vehicle_rows.append({
                'resident': r,
                'plates': top_vehicles,
                'has_active': has_active,
            })

        vpage = request.GET.get('vpage', 1)
        vehicle_paginator = Paginator(vehicle_rows, 10)
        vehicles_page = vehicle_paginator.get_page(vpage)

    # Add Resident (modal submit)
    if request.method == 'POST' and request.POST.get('action') == 'add_resident':
        form = ResidentForm(request.POST, request.FILES)
        if form.is_valid():
            resident = form.save()

            # Optional: Provision to FR terminal if face image provided
            face_file = form.cleaned_data.get('face_image')
            fr_start = form.cleaned_data.get('fr_start_time')
            fr_end = form.cleaned_data.get('fr_end_time')

            if face_file:
                try:
                    # Normalize validity times
                    now = timezone.now()
                    # Make aware if naive, then convert to local timezone consistently
                    if fr_start:
                        aware_start = timezone.make_aware(fr_start) if fr_start.tzinfo is None and settings.USE_TZ else fr_start
                        local_start = timezone.localtime(aware_start) if settings.USE_TZ else aware_start
                    else:
                        local_start = timezone.localtime(now) if settings.USE_TZ else now

                    if fr_end:
                        aware_end = timezone.make_aware(fr_end) if fr_end.tzinfo is None and settings.USE_TZ else fr_end
                        local_end = timezone.localtime(aware_end) if settings.USE_TZ else aware_end
                    else:
                        local_end = local_start + timezone.timedelta(days=365)
                    if local_end <= local_start:
                        local_end = local_start + timezone.timedelta(hours=1)

                    # Employee number: stable per resident
                    employee_no = str(resident.id).zfill(6)
                    manager = HikvisionTerminalManager()
                    # Create/Update user record with rights (face-only by default)
                    created = manager.create_user_json_with_rights_and_pin(
                        employee_no=employee_no,
                        name=resident.full_name,
                        start_time=local_start,
                        end_time=local_end,
                        pin=None,
                    )
                    # Upload face image (convert to bytes)
                    image_bytes = face_file.read()
                    uploaded = manager.upload_face_image(employee_no=employee_no, image_content=image_bytes)
                    # Enable face access right if supported
                    try:
                        manager.enable_face_access(employee_no)
                    except Exception:
                        pass
                    if created and uploaded:
                        resident.terminal_user_id = employee_no
                        resident.fr_valid_from = local_start
                        resident.fr_valid_until = local_end
                        resident.save(update_fields=['terminal_user_id', 'fr_valid_from', 'fr_valid_until'])
                        messages.success(request, f"Resident '{resident.full_name}' added and face provisioned to FR terminal.")
                    else:
                        messages.warning(request, f"Resident '{resident.full_name}' added, but FR provisioning failed. Please retry from resident detail.")
                except Exception as e:
                    messages.warning(request, f"Face provisioning error: {e}")

            else:
                messages.success(request, f"Resident '{resident.full_name}' has been added.")

            return redirect(f"{reverse('residents:management')}?tab=resident")
        else:
            messages.error(request, 'Failed to add resident. Please check your input.')

    # Edit Resident
    if request.method == 'POST' and request.POST.get('action') == 'edit_resident':
        resident_id = request.POST.get('resident_id')
        resident = get_object_or_404(Resident, id=resident_id)
        form = ResidentForm(request.POST, request.FILES, instance=resident)
        if form.is_valid():
            resident = form.save()

            # Handle optional face upload and FR validity updates
            face_file = form.cleaned_data.get('face_image')
            fr_start = form.cleaned_data.get('fr_start_time')
            fr_end = form.cleaned_data.get('fr_end_time')

            try:
                # Normalize validity times similar to add flow
                now = timezone.now()
                if fr_start:
                    aware_start = timezone.make_aware(fr_start) if fr_start.tzinfo is None and settings.USE_TZ else fr_start
                    local_start = timezone.localtime(aware_start) if settings.USE_TZ else aware_start
                else:
                    local_start = timezone.localtime(now) if settings.USE_TZ else now

                if fr_end:
                    aware_end = timezone.make_aware(fr_end) if fr_end.tzinfo is None and settings.USE_TZ else fr_end
                    local_end = timezone.localtime(aware_end) if settings.USE_TZ else aware_end
                else:
                    local_end = local_start + timezone.timedelta(days=365)
                if local_end <= local_start:
                    local_end = local_start + timezone.timedelta(hours=1)

                employee_no = str(resident.id).zfill(6)
                manager = HikvisionTerminalManager()
                # Update user record with rights window
                manager.create_user_json_with_rights_and_pin(
                    employee_no=employee_no,
                    name=resident.full_name,
                    start_time=local_start,
                    end_time=local_end,
                    pin=None,
                )

                if face_file:
                    image_bytes = face_file.read()
                    uploaded = manager.upload_face_image(employee_no=employee_no, image_content=image_bytes)
                    try:
                        manager.enable_face_access(employee_no)
                    except Exception:
                        pass
                    if uploaded:
                        resident.terminal_user_id = employee_no
                        messages.success(request, "Face image uploaded and FR provisioning updated.")

                # Persist FR validity fields even if no photo changed
                resident.fr_valid_from = local_start
                resident.fr_valid_until = local_end
                resident.save(update_fields=['fr_valid_from', 'fr_valid_until', 'terminal_user_id'])
            except Exception as e:
                messages.warning(request, f"Update succeeded, but FR provisioning error: {e}")

            messages.success(request, f"Resident '{resident.full_name}' has been updated.")
            return redirect(f"{reverse('residents:management')}?tab=resident&edit_resident_id={resident.id}")
        else:
            messages.error(request, 'Failed to update resident. Please check your input.')

    # Delete Resident
    if request.method == 'POST' and request.POST.get('action') == 'delete_resident':
        resident_id = request.POST.get('resident_id')
        resident = get_object_or_404(Resident, id=resident_id)
        resident.delete()
        messages.success(request, 'Resident has been deleted.')
        return redirect(f"{reverse('residents:management')}?tab=resident")

    # Add Vehicle (modal submit)
    if request.method == 'POST' and request.POST.get('action') == 'add_vehicle':
        resident_id = request.POST.get('resident_id')
        resident = get_object_or_404(Resident, id=resident_id)
        if resident.vehicles.filter(is_active=True).count() >= 5:
            messages.error(request, f"Resident '{resident.full_name}' already has 5 active vehicles.")
        else:
            form = ResidentVehicleForm(request.POST)
            if form.is_valid():
                vehicle = form.save(commit=False)
                vehicle.resident = resident
                vehicle.created_by = request.user
                vehicle.save()

                # Auto-whitelist to camera using start & end
                now = timezone.now()
                begin_time = vehicle.start_time or now
                # Clamp begin_time to now for immediate activation to avoid "To be Activated"
                if begin_time > now:
                    begin_time = now
                # Determine end_time and ensure it is after begin_time
                end_time = vehicle.end_time or (begin_time + timezone.timedelta(hours=24))
                if end_time <= begin_time:
                    end_time = begin_time + timezone.timedelta(hours=1)
                expiry_hours = max(1, int((end_time - begin_time).total_seconds() // 3600))

                manager = ALPRCameraManager()
                result = manager.add_to_whitelist(
                    vehicle.plate_number,
                    visitor_name=resident.full_name,
                    expiry_hours=expiry_hours,
                    begin_time=begin_time,
                    end_time=end_time,
                    camera_target='resident',
                )
                if result.get('success'):
                    messages.success(request, f"Vehicle {vehicle.plate_number} whitelisted: {result.get('message')}")
                else:
                    messages.warning(request, f"Vehicle {vehicle.plate_number} failed to whitelist: {result.get('error')}")

                return redirect(f"{reverse('residents:management')}?tab=vehicle")
            else:
                messages.error(request, 'Failed to add vehicle. Please check your input.')

    # Edit Vehicle
    if request.method == 'POST' and request.POST.get('action') == 'edit_vehicle':
        vehicle_id = request.POST.get('vehicle_id')
        vehicle = get_object_or_404(ResidentVehicle, id=vehicle_id)
        form = ResidentVehicleForm(request.POST, instance=vehicle)
        if form.is_valid():
            form.save()
            messages.success(request, f"Vehicle '{vehicle.plate_number}' has been updated.")
            return redirect(f"{reverse('residents:management')}?tab=vehicle")
        else:
            messages.error(request, 'Failed to update vehicle. Please check your input.')

    # Delete Vehicle
    if request.method == 'POST' and request.POST.get('action') == 'delete_vehicle':
        vehicle_id = request.POST.get('vehicle_id')
        vehicle = get_object_or_404(ResidentVehicle, id=vehicle_id)
        vehicle.delete()
        messages.success(request, 'Vehicle has been deleted.')
        return redirect(f"{reverse('residents:management')}?tab=vehicle")

    # Address configuration for form select options (Tower/Level/Unit)
    address_config = AddressConfiguration.objects.first()

    # Edit modal context via GET (preload forms)
    edit_resident_id = request.GET.get('edit_resident_id')
    edit_vehicle_id = request.GET.get('edit_vehicle_id')
    edit_resident_form = None
    edit_vehicle_form = None
    if edit_resident_id:
        try:
            edit_resident_form = ResidentForm(instance=Resident.objects.get(id=edit_resident_id))
        except Resident.DoesNotExist:
            edit_resident_form = None
    if edit_vehicle_id:
        try:
            edit_vehicle_form = ResidentVehicleForm(instance=ResidentVehicle.objects.get(id=edit_vehicle_id))
        except ResidentVehicle.DoesNotExist:
            edit_vehicle_form = None

    context = {
        'active_tab': active_tab,
        'residents': residents,
        'residents_page': residents_page,
        'vehicles': vehicles,
        'vehicle_rows': vehicle_rows,
        'vehicles_page': vehicles_page,
        'resident_form': ResidentForm(),
        'vehicle_form': ResidentVehicleForm(),
        'edit_resident_form': edit_resident_form,
        'edit_vehicle_form': edit_vehicle_form,
        'address_config': address_config,
        'filters': {
            'q': q,
            'status': status,
            'tower': tower,
            'level': level,
            'unit': unit,
        }
    }
    return render(request, 'residents/management.html', context)