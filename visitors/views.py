from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.http import HttpResponseForbidden, JsonResponse
from django.urls import reverse
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from accounts.decorators import security_officer_required, staff_or_above_required, management_or_admin_required
import uuid
import random
import string
import secrets
import requests
import base64
from django.core.files.base import ContentFile
from .models import Visitor, PreRegistration
from site_settings.models import Site, VisitorCategory, SiteConfiguration, DahuaConfiguration, HikvisionConfiguration, AddressConfiguration
from django.contrib.auth.models import User
from django.core.cache import cache
from .hikvision_utils import HikvisionTerminalManager
try:
    import cv2
    import numpy as np
    _CV2_AVAILABLE = True
except Exception:
    _CV2_AVAILABLE = False
from .models import Visitor, VisitorCategory





@login_required
def checkout_visitor(request, visitor_id):
    user_profile = request.user.profile
    
    visitor = get_object_or_404(Visitor, id=visitor_id)
    
    if visitor.check_out_time:
        messages.warning(request, f"Visitor {visitor.full_name} has already been checked out")
    else:
        visitor.check_out_time = timezone.now()
        visitor.save()
        messages.success(request, f"Visitor {visitor.full_name} has been checked out successfully")
    
    return redirect('dashboard:index')

@login_required
@staff_or_above_required
def pre_register_visitor(request):
    user_profile = request.user.profile
    
    categories = VisitorCategory.objects.all()
    # Load address configuration for dropdown options (Tower/Level/Unit)
    address_config = AddressConfiguration.objects.first()
    
    if request.method == 'POST':
        # Process form data
        full_name = request.POST.get('full_name')
        contact_number = request.POST.get('phone')
        company = request.POST.get('company')
        category_id = request.POST.get('category')
        purpose = request.POST.get('purpose')
        expected_date = request.POST.get('expected_date')
        expected_time = request.POST.get('expected_time')
        tower = request.POST.get('tower')
        level = request.POST.get('level')
        unit = request.POST.get('unit')
        
        category = get_object_or_404(VisitorCategory, id=category_id)
        
        # Parse expected arrival date and time
        from django.utils import timezone
        import datetime
        expected_arrival_date = None
        expected_arrival_time = None
        if expected_date:
            try:
                expected_arrival_date = datetime.datetime.strptime(expected_date, '%Y-%m-%d').date()
            except ValueError:
                pass
        if expected_time:
            try:
                expected_arrival_time = datetime.datetime.strptime(expected_time, '%H:%M').time()
            except ValueError:
                pass
        
        # Create visitor first (for pre-registration) - don't set check_in_time yet
        visitor = Visitor()
        visitor.full_name = full_name
        visitor.contact_number = contact_number
        visitor.company = company
        visitor.category = category
        visitor.purpose = purpose
        visitor.tower = tower
        visitor.level = level
        visitor.unit = unit
        visitor.ic_last_digits = '0000'  # Default for pre-registration
        visitor.is_pre_registered = True
        visitor.check_in_time = None  # Will be set when verified by security
        visitor.save()
        
        # Create pre-registration with expiry (2 hours from now for visitor to complete)
        expires_at = timezone.now() + datetime.timedelta(hours=2)
        
        pre_registration = PreRegistration.objects.create(
            visitor=visitor,
            registered_by=request.user,
            expected_arrival_date=expected_arrival_date,
            expected_arrival_time=expected_arrival_time,
            expires_at=expires_at
        )
        
        # Generate QR code with 6-digit OTP
        import qrcode
        from io import BytesIO
        from django.core.files import File
        
        # Create QR code with 6-digit OTP directly
        qr_data = pre_registration.otp
        
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(qr_data)
        qr.make(fit=True)
        
        qr_img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        qr_img.save(buffer, format='PNG')
        buffer.seek(0)
        
        pre_registration.qr_code.save(
            f'qr_otp_{pre_registration.otp}.png',
            File(buffer),
            save=True
        )
        
        # Build the unique pre-registration URL for the visitor to complete details
        try:
            pre_reg_url = request.build_absolute_uri(
                reverse('visitors:pre_register_form', args=[pre_registration.unique_link])
            )
        except Exception:
            pre_reg_url = None
        
        messages.success(
            request, 
            (
                f"Visitor {full_name} has been pre-registered successfully. "
                + (f"Pre-registration link: {pre_reg_url}" if pre_reg_url else "")
            )
        )
        # Stay on the same page after successful submission
        return redirect('visitors:pre_register')
    
    # Get recent pre-registrations for the right column
    profile = getattr(request.user, 'profile', None)
    role_value = None
    if profile and getattr(profile, 'role', None):
        role_value = str(profile.role).strip().lower().replace(' ', '_')

    recent_qs = PreRegistration.objects.select_related(
        'visitor', 'registered_by', 'visitor__category'
    ).order_by('-created_at')

    # Staff should only see their own recent pre-registrations
    if (profile and getattr(profile, 'is_staff', False)) or role_value == 'staff':
        recent_qs = recent_qs.filter(registered_by=request.user)

    recent_pre_registrations = list(recent_qs[:10])  # Show last 10 pre-registrations
    # Attach absolute pre-registration link to each item for clipboard copy in UI
    for pr in recent_pre_registrations:
        try:
            pr.pre_reg_link = request.build_absolute_uri(
                reverse('visitors:pre_register_form', args=[pr.unique_link])
            )
        except Exception:
            pr.pre_reg_link = reverse('visitors:pre_register_form', args=[pr.unique_link])

    context = {
        'categories': categories,
        'recent_pre_registrations': recent_pre_registrations,
        'address_config': address_config,
    }
    
    return render(request, 'visitors/pre_register.html', context)

def pre_register_form(request, unique_link):
    pre_registration = get_object_or_404(PreRegistration, unique_link=unique_link)
    
    if pre_registration.is_used:
        return render(request, 'visitors/pre_register_used.html')
    
    if pre_registration.is_expired:
        return render(request, 'visitors/pre_register_expired.html')
    
    # Note: QR/OTP time window validation is only for verification, not form access
    # Form access is only limited by the 2-hour expiry from creation
    
    visitor = pre_registration.visitor
    
    if request.method == 'POST':
        # Process form data - visitor can only edit IC and vehicle number
        vehicle_number = request.POST.get('vehicle_number')
        ic_last_digits = request.POST.get('ic_last_digits')
        
        # Update visitor record (only IC and vehicle number)
        visitor.vehicle_number = vehicle_number
        visitor.ic_last_digits = ic_last_digits or '0000'
        visitor.save()
        
        # Auto-whitelist vehicle plate if provided
        whitelist_result = None
        if vehicle_number and vehicle_number.strip():
            from .alpr_utils import auto_whitelist_visitor_plate
            
            # Calculate expiry based on expected arrival date
            expiry_hours = 24  # Default 24 hours
            if pre_registration.expected_arrival_date:
                from datetime import datetime, timedelta
                expected_arrival = datetime.combine(
                    pre_registration.expected_arrival_date,
                    pre_registration.expected_arrival_time or datetime.min.time()
                )
                # Whitelist until 3 hours after expected arrival
                expiry_time = expected_arrival + timedelta(hours=3)
                now = datetime.now()
                if expiry_time > now:
                    expiry_hours = max(1, int((expiry_time - now).total_seconds() / 3600))
            
            whitelist_result = auto_whitelist_visitor_plate(
                visitor=visitor,
                created_by=pre_registration.registered_by,
                expiry_hours=expiry_hours
            )
        
        # Note: Tower, Level, Unit are set by host/admin and cannot be changed by visitor
        # Note: Pre-registration will be marked as used only after security officer verification
        # Note: Pass number will be generated only after security officer verification
        
        context = {
            'visitor': visitor,
            'pre_registration': pre_registration,
            'qr_code_url': pre_registration.qr_code.url if pre_registration.qr_code else None,
            'whitelist_result': whitelist_result
        }
        
        return render(request, 'visitors/pre_register_success.html', context)
    
    context = {
        'pre_registration': pre_registration,
        'visitor': visitor
    }
    
    return render(request, 'visitors/pre_register_form.html', context)

@login_required
@security_officer_required
@require_GET
def lookup_visitor(request):
    """Return the most recent Visitor data (excluding purpose/pass) by IC last digits or phone.
    Query params:
      - ic: last 1-4 alphanumeric characters
      - phone: contact number (exact match after trimming)
    """
    ic = (request.GET.get('ic') or '').strip()
    phone = (request.GET.get('phone') or '').strip()

    if not ic and not phone:
        return JsonResponse({'success': False, 'message': 'No query provided'}, status=400)

    # Normalize IC to alphanumeric, up to 4 chars
    ic_norm = ''.join(ch for ch in ic if ch.isalnum())[:4]

    qs = Visitor.objects.all()

    # Prefer combined match if both provided; otherwise fallback progressively
    visitor = None
    try:
        if phone and ic_norm:
            visitor = qs.filter(contact_number__iexact=phone, ic_last_digits__iexact=ic_norm).order_by('-created_at').first()
        if not visitor and phone:
            visitor = qs.filter(contact_number__iexact=phone).order_by('-created_at').first()
        if not visitor and ic_norm:
            visitor = qs.filter(ic_last_digits__iexact=ic_norm).order_by('-created_at').first()
    except Exception:
        visitor = None

    if not visitor:
        return JsonResponse({'success': False, 'found': False})

    data = {
        'full_name': visitor.full_name or '',
        'contact_number': visitor.contact_number or '',
        'company': visitor.company or '',
        'vehicle_number': visitor.vehicle_number or '',
        'tower': visitor.tower or '',
        'level': visitor.level or '',
        'unit': visitor.unit or '',
        'category_id': visitor.category.id if visitor.category else None,
        'category_name': visitor.category.name if visitor.category else None,
        # Intentionally exclude: purpose, pass_number
    }

    return JsonResponse({'success': True, 'found': True, 'data': data})

@login_required
@security_officer_required
def verify_visitor(request):
    if request.method == 'POST':
        # Detect AJAX/JSON intent
        wants_json = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax') == '1'

        # Tiny per-IP and per-user throttle (e.g., 10 attempts per 60 seconds)
        try:
            ip = (request.META.get('HTTP_X_FORWARDED_FOR') or '').split(',')[0].strip() or request.META.get('REMOTE_ADDR', '') or 'unknown'
            user_id = getattr(request.user, 'id', 'anon')
            cache_key = f"otp_verify:{ip}:{user_id}"
            window_seconds = 60
            max_attempts = 10
            attempts = cache.get(cache_key, 0)
            if attempts >= max_attempts:
                if wants_json:
                    return JsonResponse({'status': 'error', 'code': 'rate_limited', 'message': 'Too many attempts. Please wait a minute.'}, status=429)
                messages.error(request, 'Too many attempts. Please wait a minute.')
                return redirect('verify')
            else:
                cache.set(cache_key, attempts + 1, timeout=window_seconds)
        except Exception:
            # Fail open: do not block verification if cache unavailable
            pass

        try:
            otp = request.POST.get('otp')
            if not otp or len(otp) != 6:
                if wants_json:
                    return JsonResponse({
                        'status': 'error',
                        'code': 'invalid_input',
                        'message': 'Please provide a valid 6-digit OTP.'
                    }, status=400)
                else:
                    messages.error(request, 'Please provide a valid 6-digit OTP.')
                    return redirect('verify')

            from .models import PreRegistration, Visitor
            prereg = PreRegistration.objects.filter(otp=otp).select_related('visitor').first()
            if not prereg:
                if wants_json:
                    return JsonResponse({'status': 'error', 'code': 'not_found', 'message': 'Invalid or unregistered OTP.'}, status=404)
                messages.error(request, 'Invalid or unregistered OTP.')
                return redirect('verify')

            if prereg.is_used:
                if wants_json:
                    return JsonResponse({'status': 'error', 'code': 'otp_used', 'message': 'This OTP has already been used.'}, status=400)
                messages.error(request, 'This OTP has already been used.')
                return redirect('verify')

            # Expiry checks
            now = timezone.now()
            if prereg.expires_at and now > prereg.expires_at:
                if wants_json:
                    return JsonResponse({'status': 'error', 'code': 'expired', 'message': 'This OTP has expired.'}, status=400)
                messages.error(request, 'This OTP has expired.')
                return redirect('verify')

            # Success: mark used and check-in
            prereg.is_used = True
            prereg.verified_by = request.user
            prereg.verified_at = now
            prereg.save()

            visitor = prereg.visitor
            if visitor and not visitor.check_in_time:
                visitor.check_in_time = now
                visitor.save(update_fields=['check_in_time'])

            print_url = request.build_absolute_uri(reverse('visitors:print_pass', args=[visitor.id])) if visitor else None

            if wants_json:
                # Build host and expected arrival details
                host = ''
                expected_arrival = ''
                try:
                    host_user = prereg.registered_by
                    host = (host_user.get_full_name() or host_user.username) if host_user else ''
                except Exception:
                    host = ''
                try:
                    if prereg.expected_arrival_date:
                        if prereg.expected_arrival_time:
                            expected_arrival = f"{prereg.expected_arrival_date.strftime('%Y-%m-%d')} {prereg.expected_arrival_time.strftime('%H:%M')}"
                        else:
                            expected_arrival = prereg.expected_arrival_date.strftime('%Y-%m-%d')
                except Exception:
                    expected_arrival = ''

                # Build visitor payload for modal details
                visitor_payload = {}
                if visitor:
                    visitor_payload = {
                        'full_name': visitor.full_name or '',
                        'company': visitor.company or '',
                        'category': (visitor.category.name if getattr(visitor, 'category', None) else ''),
                        'contact_number': visitor.contact_number or '',
                        'pass_number': visitor.pass_number or '',
                        'check_in_time': timezone.localtime(visitor.check_in_time).strftime('%Y-%m-%d %H:%M') if visitor.check_in_time else '',
                        'host': host,
                        'expected_arrival': expected_arrival,
                    }

                return JsonResponse({
                    'status': 'success',
                    'message': 'OTP verified. Visitor checked in.',
                    'print_url': print_url,
                    'visitor': visitor_payload,
                })

            messages.success(request, 'OTP verified. Visitor checked in.')
            return redirect('visitors:print_pass', visitor_id=visitor.id)
        except Exception as e:
            messages.error(request, 'An error occurred during verification.')
            return redirect('verify')

    # GET fallthrough
    return render(request, 'visitors/verify.html')

@login_required
def print_visitor_pass(request, visitor_id):
    """Print visitor pass with QR code"""
    visitor = get_object_or_404(Visitor.objects.select_related('pre_registration__registered_by'), id=visitor_id)
    user_profile = request.user.profile
    
    # Generate QR code for visitor pass
    import qrcode
    from io import BytesIO
    import base64
    
    # QR code data - visitor information
    qr_data = f"VMS-PASS:{visitor.pass_number}|{visitor.full_name}|VMS|{timezone.localtime(visitor.check_in_time).strftime('%Y-%m-%d %H:%M')}"
    
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(qr_data)
    qr.make(fit=True)
    
    qr_img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    qr_img.save(buffer, format='PNG')
    buffer.seek(0)
    
    # Convert to base64 for embedding in template
    qr_code_base64 = base64.b64encode(buffer.getvalue()).decode()
    
    context = {
        'visitor': visitor,
        'qr_code_base64': qr_code_base64,
        'print_time': timezone.now(),
    }
    
    return render(request, 'visitors/print_pass.html', context)

@login_required
@require_POST
def bulk_checkout(request):
    """Handle bulk checkout of multiple visitors"""
    # Check if user has permission
    if not (hasattr(request.user, 'profile') and 
            request.user.profile.role in ['admin', 'site_client', 'security_officer']):
        messages.error(request, 'You do not have permission to perform this action.')
        return redirect('dashboard:index')
    
    visitor_ids = request.POST.getlist('visitor_ids')
    
    if not visitor_ids:
        messages.error(request, 'No visitors selected for checkout.')
        return redirect('dashboard:index')
    
    try:
        # Get visitors that belong to user's site (if applicable)
        visitors_query = Visitor.objects.filter(
            id__in=visitor_ids,
            check_out_time__isnull=True  # Only active visitors
        )
        
        # No site filtering needed in single-site setup
        
        # Update checkout time for selected visitors
        updated_count = visitors_query.update(check_out_time=timezone.now())
        
        if updated_count > 0:
            messages.success(request, f'Successfully checked out {updated_count} visitor(s).')
        else:
            messages.warning(request, 'No visitors were checked out. They may have already been checked out or you may not have permission.')
            
    except Exception as e:
        messages.error(request, f'An error occurred during bulk checkout: {str(e)}')
    
    return redirect('dashboard:index')

@login_required
@require_POST
def delete_visitor(request, visitor_id):
    """Delete a visitor record - Admin only"""
    # Check if user is admin
    if not (hasattr(request.user, 'profile') and request.user.profile.role == 'admin'):
        messages.error(request, 'You do not have permission to delete visitor records.')
        return redirect('dashboard:index')
    
    try:
        visitor = get_object_or_404(Visitor, id=visitor_id)
        visitor_name = visitor.full_name
        visitor.delete()
        messages.success(request, f'Visitor record for {visitor_name} has been deleted successfully.')
    except Exception as e:
        messages.error(request, f'An error occurred while deleting visitor: {str(e)}')
    
    return redirect('dashboard:index')

@login_required
@require_POST
def bulk_delete_visitors(request):
    """Bulk delete visitor records - Admin only"""
    # Check if user is admin
    if not (hasattr(request.user, 'profile') and request.user.profile.role == 'admin'):
        messages.error(request, 'You do not have permission to delete visitor records.')
        return redirect('dashboard:index')
    
    visitor_ids = request.POST.getlist('visitor_ids')
    
    if not visitor_ids:
        messages.error(request, 'No visitors selected for deletion.')
        return redirect('dashboard:index')
    
    try:
        visitors_query = Visitor.objects.filter(id__in=visitor_ids)
        deleted_count = visitors_query.count()
        visitors_query.delete()
        
        if deleted_count > 0:
            messages.success(request, f'Successfully deleted {deleted_count} visitor record(s).')
        else:
            messages.warning(request, 'No visitor records were deleted.')
            
    except Exception as e:
        messages.error(request, f'An error occurred during bulk deletion: {str(e)}')
    
    return redirect('dashboard:index')

@login_required
def pre_registration_list(request):
    """Display list of pre-registered visitors with creator information"""
    user_profile = request.user.profile
    
    # Get filter parameters
    search = request.GET.get('search', '')
    status = request.GET.get('status', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    
    # Build query for pre-registrations based on role
    pre_registrations = PreRegistration.objects.select_related(
        'visitor', 'registered_by', 'visitor__category'
    )
    
    # Role-based filtering
    if user_profile.role == 'staff':
        # Staff can only see their own pre-registrations
        pre_registrations = pre_registrations.filter(registered_by=request.user)
    elif user_profile.role == 'management':
        # Management can see their own and staff pre-registrations
        pre_registrations = pre_registrations.filter(
            registered_by__profile__role__in=['management', 'staff']
        )
    # Admin and Security Officer can see all
    
    pre_registrations = pre_registrations.order_by('-created_at')
    
    # Apply search filter
    if search:
        from django.db.models import Q
        pre_registrations = pre_registrations.filter(
            Q(visitor__full_name__icontains=search) |
            Q(visitor__company__icontains=search) |
            Q(visitor__contact_number__icontains=search) |
            Q(registered_by__username__icontains=search) |
            Q(registered_by__first_name__icontains=search) |
            Q(registered_by__last_name__icontains=search)
        )
    
    # Apply status filter
    if status == 'used':
        pre_registrations = pre_registrations.filter(is_used=True)
    elif status == 'unused':
        pre_registrations = pre_registrations.filter(is_used=False)
    elif status == 'expired':
        pre_registrations = pre_registrations.filter(expires_at__lt=timezone.now(), is_used=False)
    
    # Apply date filter
    if date_from:
        try:
            from datetime import datetime
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            pre_registrations = pre_registrations.filter(created_at__date__gte=date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            from datetime import datetime
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            pre_registrations = pre_registrations.filter(created_at__date__lte=date_to_obj)
        except ValueError:
            pass
    
    # Pagination
    from django.core.paginator import Paginator
    paginator = Paginator(pre_registrations, 25)  # Show 25 pre-registrations per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'pre_registrations': page_obj.object_list,
        'total_count': pre_registrations.count(),
        'filters': {
            'search': search,
            'status': status,
            'date_from': date_from,
            'date_to': date_to,
        }
    }
    
    return render(request, 'visitors/pre_registration_list.html', context)

@login_required
@security_officer_required
def verify_pre_registration(request, pre_reg_id):
    prereg = get_object_or_404(PreRegistration, id=pre_reg_id)
    wants_json = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax') == '1'

    if request.method == 'POST':
        # Throttle OTP verification attempts
        user_id = request.user.id
        client_ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', ''))
        throttle_key = f"verify_pre_reg_{user_id}_{client_ip}"
        attempts = cache.get(throttle_key, 0)
        
        if attempts >= 10:  # 10 attempts per 60 seconds
            if wants_json:
                return JsonResponse({'status': 'error', 'code': 'rate_limited', 'message': 'Too many verification attempts. Please wait a moment.'}, status=429)
            messages.error(request, 'Too many verification attempts. Please wait a moment.')
            return redirect('verify_pre_registration', pre_reg_id=pre_reg_id)
        
        cache.set(throttle_key, attempts + 1, 60)  # Set for 60 seconds
        
        action = request.POST.get('action')
        now = timezone.now()
        try:
            if action == 'verify':
                prereg.is_verified = True
                prereg.verified_by = request.user
                prereg.verified_at = now
                prereg.is_used = True
                prereg.save()

                visitor = prereg.visitor
                if visitor and not visitor.check_in_time:
                    visitor.check_in_time = now
                    visitor.save(update_fields=['check_in_time'])
                print_url = request.build_absolute_uri(reverse('print_pass', args=[visitor.id])) if visitor else None

                if wants_json:
                    return JsonResponse({
                        'status': 'success',
                        'message': 'Pre-registration verified successfully.',
                        'visitor': {
                            'id': visitor.id if visitor else None,
                            'full_name': visitor.full_name if visitor else '',
                            'company': getattr(visitor, 'company', ''),
                            'category': getattr(visitor, 'category', ''),
                            'contact_number': getattr(visitor, 'contact_number', ''),
                            'pass_number': getattr(visitor, 'pass_number', ''),
                            'check_in_time': timezone.localtime(visitor.check_in_time).strftime('%Y-%m-%d %H:%M') if visitor and visitor.check_in_time else ''
                        },
                        'print_url': print_url
                    })

                messages.success(request, 'Pre-registration verified successfully.')
                return redirect('verify_pre_registration', pre_reg_id=pre_reg_id)

            elif action == 'reject':
                prereg.is_verified = False
                prereg.is_used = False
                prereg.verified_by = request.user
                prereg.verified_at = now
                prereg.save(update_fields=['is_verified', 'is_used', 'verified_by', 'verified_at'])

                if wants_json:
                    return JsonResponse({'status': 'error', 'code': 'rejected', 'message': 'Pre-registration rejected.'}, status=200)

                messages.error(request, 'Pre-registration rejected.')
                return redirect('verify_pre_registration', pre_reg_id=pre_reg_id)

            else:
                if wants_json:
                    return JsonResponse({'status': 'error', 'code': 'invalid_action', 'message': 'Invalid action.'}, status=400)
                messages.error(request, 'Invalid action.')
                return redirect('verify_pre_registration', pre_reg_id=pre_reg_id)
        except Exception:
            if wants_json:
                return JsonResponse({'status': 'error', 'code': 'server_error', 'message': 'An error occurred processing the request.'}, status=500)
            messages.error(request, 'An error occurred processing the request.')
            return redirect('verify_pre_registration', pre_reg_id=pre_reg_id)

    return render(request, 'visitors/verify_pre_registration.html', {'preregistration': prereg})


@csrf_exempt
@require_POST
@login_required
def scan_plate_api(request):
    """
    API endpoint untuk scan plate dari kamera ALPR Dahua
    """
    try:
        # Tentukan site aktif dan cek feature flag ALPR/Whitelist
        site = Site.objects.filter(is_active=True).first()
        site_cfg = None
        try:
            site_cfg = SiteConfiguration.objects.filter(site=site).first()
        except Exception:
            site_cfg = None
        if not site_cfg or not getattr(site_cfg, 'enable_alpr_whitelist', False):
            return JsonResponse({
                'success': False,
                'error': 'ALPR/Whitelist integration disabled by administrator.'
            }, status=403)

        # Ambil konfigurasi kamera per-site dan cek is_enabled
        try:
            camera_config = DahuaConfiguration.objects.filter(site=site).first() or DahuaConfiguration.objects.first()
            if not camera_config or not getattr(camera_config, 'is_enabled', False):
                return JsonResponse({
                    'success': False,
                    'error': 'ALPR camera integration is disabled or not configured.'
                }, status=403)
        except Exception:
            return JsonResponse({
                'success': False,
                'error': 'Camera configuration not found. Please configure ALPR camera in admin panel.'
            }, status=400)
        
        # Endpoint untuk mengambil snapshot dari kamera (ikut port dari camera_url)
        snapshot_url = f"{camera_config.camera_url}/cgi-bin/snapshot.cgi"
        
        # Buat request dengan Digest Authentication
        try:
            response = requests.get(
                snapshot_url,
                auth=requests.auth.HTTPDigestAuth(camera_config.username, camera_config.password),
                timeout=camera_config.timeout_seconds
            )
            
            if response.status_code == 200:
                # Encode image ke base64 untuk dikirim ke frontend
                image_base64 = base64.b64encode(response.content).decode('utf-8')
                
                # Simulasi ekstraksi plate number (dalam implementasi nyata, ini akan menggunakan OCR atau API ALPR)
                # Untuk demo, kita generate plate number random
                plate_number = f"B{random.randint(1000, 9999)}ABC"
                
                return JsonResponse({
                    'success': True,
                    'plate_number': plate_number,
                    'image_base64': image_base64,
                    'message': 'Plate scanned successfully'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': f'Failed to capture image from camera. Status: {response.status_code}'
                }, status=400)
                
        except requests.exceptions.Timeout:
            return JsonResponse({
                'success': False,
                'error': 'Camera connection timeout. Please check camera connectivity.'
            }, status=408)
        except requests.exceptions.ConnectionError:
            return JsonResponse({
                'success': False,
                'error': 'Cannot connect to camera. Please check IP address and network connectivity.'
            }, status=503)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Camera communication error: {str(e)}'
            }, status=500)
            
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Server error: {str(e)}'
        }, status=500)


@login_required
@staff_or_above_required
@csrf_exempt
@require_POST
def whitelist_plate_api(request):
    """
    API endpoint to manually whitelist a plate number
    """
    try:
        import json
        data = json.loads(request.body)
        plate_number = data.get('plate_number', '').strip()
        visitor_id = data.get('visitor_id')
        visitor_name = data.get('visitor_name', None)
        expiry_hours = data.get('expiry_hours', 24)
        
        if not plate_number:
            return JsonResponse({
                'success': False,
                'error': 'Plate number is required'
            }, status=400)
        
        # Get visitor if provided
        visitor = None
        if visitor_id:
            try:
                visitor = Visitor.objects.get(id=visitor_id)
            except Visitor.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': 'Visitor not found'
                }, status=404)
        
        # Use auto-whitelist function if visitor provided, otherwise use camera manager directly
        if visitor:
            from .alpr_utils import auto_whitelist_visitor_plate
            result = auto_whitelist_visitor_plate(
                visitor=visitor,
                created_by=request.user,
                expiry_hours=expiry_hours
            )
        else:
            from .alpr_utils import ALPRCameraManager
            from .models import ALPRWhitelist
            from django.utils import timezone
            
            # Create whitelist entry without visitor
            expires_at = timezone.now() + timezone.timedelta(hours=expiry_hours)
            whitelist_entry = ALPRWhitelist.objects.create(
                visitor=None,  # Manual whitelist without specific visitor
                plate_number=plate_number,
                expires_at=expires_at,
                created_by=request.user,
                is_active=True
            )
            
            # Sync to camera using provided visitor_name if any
            camera_manager = ALPRCameraManager()
            result = camera_manager.add_to_whitelist(
                plate_number,
                visitor_name=visitor_name,
                expiry_hours=expiry_hours
            )
            
            # Update sync status on entry
            whitelist_entry.sync_attempts += 1
            whitelist_entry.last_sync_attempt = timezone.now()
            if result.get('success'):
                whitelist_entry.synced_to_camera = True
                whitelist_entry.sync_error = None
            else:
                whitelist_entry.synced_to_camera = False
                whitelist_entry.sync_error = result.get('error')
            whitelist_entry.save()
        
        return JsonResponse(result)
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Unexpected error: {str(e)}'
        }, status=500)


@login_required
@staff_or_above_required
def whitelist_management(request):
    """
    Whitelist management interface for admins and staff
    """
    from .models import ALPRWhitelist
    from django.utils import timezone
    from django.core.paginator import Paginator
    from django.db.models import Q
    
    # Get filter parameters
    status_filter = request.GET.get('status', 'active')
    search_query = request.GET.get('search', '').strip()
    
    # Base queryset
    queryset = ALPRWhitelist.objects.select_related('visitor', 'created_by')
    
    # Apply status filter
    if status_filter == 'active':
        queryset = queryset.filter(
            is_active=True,
            expires_at__gt=timezone.now()
        )
    elif status_filter == 'expired':
        queryset = queryset.filter(
            Q(is_active=False) | Q(expires_at__lte=timezone.now())
        )
    elif status_filter == 'all':
        pass  # No filter
    
    # Apply search filter
    if search_query:
        queryset = queryset.filter(
            Q(plate_number__icontains=search_query) |
            Q(visitor__full_name__icontains=search_query) |
            Q(visitor__company__icontains=search_query)
        )
    
    # Order by most recent
    queryset = queryset.order_by('-whitelisted_at')
    
    # Pagination
    paginator = Paginator(queryset, 20)  # 20 entries per page
    page_number = request.GET.get('page')
    whitelist_entries = paginator.get_page(page_number)
    
    # Get statistics
    total_active = ALPRWhitelist.objects.filter(
        is_active=True,
        expires_at__gt=timezone.now()
    ).count()
    
    total_expired = ALPRWhitelist.objects.filter(
        Q(is_active=False) | Q(expires_at__lte=timezone.now())
    ).count()
    
    context = {
        'whitelist_entries': whitelist_entries,
        'status_filter': status_filter,
        'search_query': search_query,
        'total_active': total_active,
        'total_expired': total_expired,
        'user_role': request.user.profile.role if hasattr(request.user, 'profile') else 'staff'
    }
    
    return render(request, 'visitors/whitelist_management.html', context)


@login_required
@staff_or_above_required
@csrf_exempt
@require_POST
def remove_whitelist_api(request):
    """
    API endpoint to remove a plate from whitelist
    """
    try:
        import json
        data = json.loads(request.body)
        plate_number = data.get('plate_number', '').strip()
        whitelist_id = data.get('whitelist_id')
        
        if not plate_number and not whitelist_id:
            return JsonResponse({
                'success': False,
                'error': 'Plate number or whitelist ID is required'
            }, status=400)
        
        from .alpr_utils import ALPRCameraManager
        from .models import ALPRWhitelist
        
        # Find whitelist entry
        if whitelist_id:
            try:
                whitelist_entry = ALPRWhitelist.objects.get(id=whitelist_id)
                plate_number = whitelist_entry.plate_number
            except ALPRWhitelist.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': 'Whitelist entry not found'
                }, status=404)
        else:
            whitelist_entry = ALPRWhitelist.objects.filter(
                plate_number=plate_number,
                is_active=True
            ).first()
        
        # Remove from camera
        camera_manager = ALPRCameraManager()
        result = camera_manager.remove_from_whitelist(plate_number)
        
        # Update database
        if whitelist_entry:
            whitelist_entry.is_active = False
            whitelist_entry.save()
        
        return JsonResponse(result)
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Unexpected error: {str(e)}'
        }, status=500)


@login_required
@staff_or_above_required
@require_GET
def whitelist_status_api(request):
    """
    API endpoint to get whitelist status and entries
    """
    try:
        from .models import ALPRWhitelist
        from django.utils import timezone
        
        # Get active whitelist entries
        active_entries = ALPRWhitelist.objects.filter(
            is_active=True,
            expires_at__gt=timezone.now()
        ).select_related('visitor', 'created_by')
        
        # Get expired entries (last 24 hours)
        expired_entries = ALPRWhitelist.objects.filter(
            expires_at__lte=timezone.now(),
            expires_at__gte=timezone.now() - timezone.timedelta(hours=24)
        ).select_related('visitor', 'created_by')
        
        def serialize_entry(entry):
            return {
                'id': entry.id,
                'plate_number': entry.plate_number,
                'visitor_name': entry.visitor.full_name if entry.visitor else 'Manual Entry',
                'visitor_id': entry.visitor.id if entry.visitor else None,
                'whitelisted_at': entry.whitelisted_at.isoformat(),
                'expires_at': entry.expires_at.isoformat(),
                'is_expired': entry.is_expired,
                'synced_to_camera': entry.synced_to_camera,
                'sync_attempts': entry.sync_attempts,
                'sync_error': entry.sync_error,
                'created_by': entry.created_by.get_full_name() if entry.created_by else 'System'
            }
        
        return JsonResponse({
            'success': True,
            'active_entries': [serialize_entry(entry) for entry in active_entries],
            'expired_entries': [serialize_entry(entry) for entry in expired_entries],
            'total_active': active_entries.count(),
            'total_expired': expired_entries.count()
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Unexpected error: {str(e)}'
        }, status=500)


def _generate_random_digits(length=6):
    return ''.join(secrets.choice(string.digits) for _ in range(length))

# Self Registration: face + PIN, valid 24 hours
@csrf_exempt
def self_register(request):
    if request.method == 'GET':
        # Step 1: Info only (no camera on this page)
        from site_settings.models import AddressConfiguration
        context = {
            'visitor_categories': VisitorCategory.objects.all(),
            'address_config': AddressConfiguration.objects.first(),
        }
        return render(request, 'visitors/self_register_info.html', context)

    if request.method == 'POST':
        full_name = request.POST.get('full_name')
        contact_number = request.POST.get('contact_number')
        company = request.POST.get('company')
        category_id = request.POST.get('category')
        ic_last_digits = request.POST.get('ic_last_digits')
        tower = request.POST.get('tower')
        level = request.POST.get('level')
        unit = request.POST.get('unit')
        purpose = request.POST.get('purpose')
        vehicle_number = request.POST.get('vehicle_number')

        # Two-step: do NOT accept face image in this step
        image_content = None

        # Generate pass and PIN (PIN 4 digits for easier use)
        pass_number = _generate_random_digits(6)
        access_pin = _generate_random_digits(4)

        # Validity: start now (realtime), end at today's midnight (23:59:59 local time)
        now = timezone.now()
        local_now = timezone.localtime(now)
        end_local = local_now.replace(hour=23, minute=59, second=59, microsecond=0)
        end = end_local

        visitor = Visitor(
            full_name=full_name,
            contact_number=contact_number,
            company=company,
            category_id=category_id or None,
            ic_last_digits=ic_last_digits or '',
            tower=tower or None,
            level=level or None,
            unit=unit or None,
            purpose=purpose or None,
            vehicle_number=vehicle_number or None,
            pass_number=pass_number,
            access_pin=access_pin,
            check_in_time=now,
            check_out_time=None,
            is_pre_registered=False,
        )
        visitor.save()

        # Self Registration: disable terminal provisioning (Face Recognition terminal integration)
        # We skip creating/updating terminal user and setting PIN on device.
        # Visitor credentials are stored in the application only.
        visitor.terminal_user_id = None
        visitor.save(update_fields=['terminal_user_id'])

        # Redirect to photo capture step
        return redirect('visitors:self_register_photo', pass_number=pass_number)


def self_register_success(request, pass_number):
    visitor = Visitor.objects.filter(pass_number=pass_number).first()
    if not visitor:
        return render(request, 'visitors/self_register_success.html', {'error': 'Visitor not found'})
    return render(request, 'visitors/self_register_success.html', {
        'visitor': visitor,
        'provisioned': bool(visitor.terminal_user_id),
    })

@csrf_exempt
def self_register_photo(request, pass_number):
    visitor = Visitor.objects.filter(pass_number=pass_number).first()
    if not visitor:
        return render(request, 'visitors/self_register_photo.html', {'error': 'Visitor not found', 'pass_number': pass_number})
    return render(request, 'visitors/self_register_photo.html', {
        'visitor': visitor,
        'pass_number': pass_number,
    })

@csrf_exempt
def self_register_upload_face_api(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Method not allowed'}, status=405)
    pass_number = request.POST.get('pass_number')
    face_data_url = request.POST.get('face_image_data')
    if not pass_number or not face_data_url:
        return JsonResponse({'status': 'error', 'message': 'Missing parameters'}, status=400)
    visitor = Visitor.objects.filter(pass_number=pass_number).first()
    if not visitor:
        return JsonResponse({'status': 'error', 'message': 'Visitor not found'}, status=404)
    if not face_data_url.startswith('data:image'):
        return JsonResponse({'status': 'error', 'message': 'Invalid image data'}, status=400)
    try:
        header, b64data = face_data_url.split(',', 1)
        image_content = base64.b64decode(b64data)
    except Exception:
        return JsonResponse({'status': 'error', 'message': 'Failed to parse image'}, status=400)

    # Simple capture: accept image as-is, no validation or face detection
    processed_bytes = image_content

    # Save processed image for record
    try:
        visitor.face_image.save(f"visitor_{pass_number}.jpg", ContentFile(processed_bytes), save=True)
    except Exception:
        return JsonResponse({'status': 'error', 'message': 'Failed to save image'}, status=500)

    # Terminal upload disabled for self registration; store locally only
    return JsonResponse({'status': 'success', 'message': 'Face stored locally; terminal integration disabled'})


@csrf_exempt
def validate_photo_api(request):
    """Validate and crop a face image without uploading to terminal.
    Expects POST with 'face_image_data' (data URL base64). Returns JSON with
    'preview_data' (data:image/jpeg;base64,...) if a single face is detected.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Method not allowed'}, status=405)

    face_data_url = request.POST.get('face_image_data')
    if not face_data_url or not face_data_url.startswith('data:image'):
        return JsonResponse({'status': 'error', 'message': 'Invalid image data'}, status=400)

    # Parse base64 content
    try:
        header, b64data = face_data_url.split(',', 1)
        image_content = base64.b64decode(b64data)
    except Exception:
        return JsonResponse({'status': 'error', 'message': 'Failed to parse image'}, status=400)

    if not _CV2_AVAILABLE:
        # Fallback: accept but echo original (not ideal, but non-blocking)
        echo_b64 = base64.b64encode(image_content).decode('ascii')
        return JsonResponse({
            'status': 'success',
            'message': 'OpenCV not available; returning original image.',
            'preview_data': f'data:image/jpeg;base64,{echo_b64}',
        })

    # Run face detection and produce cropped/padded preview
    try:
        img_array = np.frombuffer(image_content, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if img is None:
            return JsonResponse({'status': 'error', 'message': 'Invalid image content'}, status=400)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        face_cascade = cv2.CascadeClassifier(cascade_path)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.3, minNeighbors=5, minSize=(60, 60))
        if len(faces) != 1:
            return JsonResponse({'status': 'error', 'message': 'Face verification failed. Upload a clear single-face photo.'}, status=400)
        (x, y, w, h) = faces[0]
        pad_x = int(0.15 * w)
        pad_y = int(0.20 * h)
        x1 = max(x - pad_x, 0)
        y1 = max(y - pad_y, 0)
        x2 = min(x + w + pad_x, img.shape[1])
        y2 = min(y + h + pad_y, img.shape[0])
        crop = img[y1:y2, x1:x2]
        target = 480
        h_c, w_c = crop.shape[:2]
        scale = target / max(h_c, w_c)
        resized = cv2.resize(crop, (int(w_c * scale), int(h_c * scale)), interpolation=cv2.INTER_AREA)
        h_r, w_r = resized.shape[:2]
        top = (target - h_r) // 2
        bottom = target - h_r - top
        left = (target - w_r) // 2
        right = target - w_r - left
        padded = cv2.copyMakeBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=[255, 255, 255])
        ok, buf = cv2.imencode('.jpg', padded, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            return JsonResponse({'status': 'error', 'message': 'Failed to encode processed image'}, status=500)
        preview_b64 = base64.b64encode(buf.tobytes()).decode('ascii')
        return JsonResponse({
            'status': 'success',
            'message': 'Face verified and cropped.',
            'preview_data': f'data:image/jpeg;base64,{preview_b64}',
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'Face processing error: {e}'}, status=500)


def self_checkout(request):
    """Self Checkout: form dengan satu field Nomor Pass untuk checkout.

    GET: Tampilkan form.
    POST: Validasi Nomor Pass dan set waktu checkout.
    """
    context = {
        'status': None,
        'message': None,
        'visitor': None,
    }

    if request.method == 'POST':
        pass_number = (request.POST.get('pass_number') or '').strip()
        if not pass_number:
            context.update({'status': 'error', 'message': 'Nomor Pass wajib diisi.'})
        else:
            # Look for active visitor with this pass number first
            visitor = Visitor.objects.filter(pass_number=pass_number, check_out_time__isnull=True).order_by('-check_in_time').first()
            if not visitor:
                # Check if visitor with this pass number exists but already checked out
                already_out = Visitor.objects.filter(pass_number=pass_number, check_out_time__isnull=False).order_by('-check_out_time').first()
                if already_out:
                    context.update({'status': 'warning', 'message': 'Pengunjung dengan Nomor Pass ini sudah checkout sebelumnya.', 'visitor': already_out})
                else:
                    context.update({'status': 'error', 'message': 'Nomor Pass tidak ditemukan.'})
            else:
                visitor.check_out_time = timezone.now()
                visitor.save(update_fields=['check_out_time'])
                context.update({'status': 'success', 'message': 'Checkout berhasil. Terima kasih!', 'visitor': visitor})

    return render(request, 'visitors/self_checkout.html', context)
