from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from datetime import datetime, timedelta
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import json
import requests
import logging
import base64
import re
from django.core.files.base import ContentFile
from django.conf import settings
from visitors.models import Visitor, OccurrenceLog


def natural_sort_key(s):
    """
    Natural sort key for sorting strings with numbers correctly.
    Example: ['A1', 'A10', 'A2'] -> ['A1', 'A2', 'A10']
    """
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(s))]

from site_settings.models import VisitorCategory, Site, SiteConfiguration, HikvisionConfiguration, DahuaConfiguration
from requests.auth import HTTPDigestAuth

# Configure logging for door control
logger = logging.getLogger(__name__)

@login_required
def index(request):
    user_profile = request.user.profile
    
    today = timezone.now().date()
    
    # Get site information (single site deployment)
    site = Site.objects.filter(is_active=True).first()
    
    # Get all visitor categories
    all_categories = VisitorCategory.objects.filter(is_active=True)
    
    # Analytics Cards Data
    # 1. Total Visitors (all time) - only category 'Visitor'
    total_visitors = Visitor.objects.filter(category__name__iexact='visitor').count()
    
    # 2. Category-specific totals (all time)
    category_totals = {}
    for category in all_categories:
        category_totals[category.name.lower()] = Visitor.objects.filter(category=category).count()
    
    # Backward compatibility for template - use direct queries for reliability
    total_contractors = Visitor.objects.filter(category__name__iexact='contractor').count()
    total_deliveries = Visitor.objects.filter(category__name__iexact='delivery').count()
    
    # 4. Overtime Visitors (not checked out after midnight)
    midnight_today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    midnight_yesterday = midnight_today - timedelta(days=1)
    
    overtime_visitors = Visitor.objects.filter(
        check_out_time__isnull=True,
        check_in_time__lt=midnight_today
    ).count()
    
    # Yesterday's overtime visitors (those who were overtime yesterday)
    overtime_visitors_yesterday = Visitor.objects.filter(
        check_in_time__lt=midnight_yesterday,
        check_out_time__gte=midnight_yesterday,
        check_out_time__lt=midnight_today
    ).count()
    
    # Today's and Yesterday's statistics
    yesterday = today - timedelta(days=1)
    
    # Today's data
    visitors_today = Visitor.objects.filter(
        category__name__iexact='visitor',
        check_in_time__isnull=False,
        check_in_time__gte=midnight_today
    ).count()
    
    # Category-specific counts for today
    category_today = {}
    for category in all_categories:
        category_today[category.name.lower()] = Visitor.objects.filter(
            category=category,
            check_in_time__isnull=False,
            check_in_time__gte=midnight_today
        ).count()
    
    # Backward compatibility for template - use direct queries for reliability
    # Debug the query to ensure we're getting the right data
    contractors_today = Visitor.objects.filter(
        category__name__iexact='contractor',
        check_in_time__isnull=False,
        check_in_time__gte=midnight_today
    ).count()
    deliveries_today = Visitor.objects.filter(
        category__name__iexact='delivery',
        check_in_time__isnull=False,
        check_in_time__gte=midnight_today
    ).count()
    
    # Yesterday's data for comparison
    visitors_yesterday = Visitor.objects.filter(
        category__name__iexact='visitor',
        check_in_time__isnull=False,
        check_in_time__gte=midnight_yesterday,
        check_in_time__lt=midnight_today
    ).count()
    
    # Category-specific counts for yesterday
    category_yesterday = {}
    for category in all_categories:
        category_yesterday[category.name.lower()] = Visitor.objects.filter(
            category=category,
            check_in_time__isnull=False,
            check_in_time__gte=midnight_yesterday,
            check_in_time__lt=midnight_today
        ).count()
    
    # Backward compatibility for template - use direct queries for reliability
    contractors_yesterday = Visitor.objects.filter(
        category__name__iexact='contractor',
        check_in_time__isnull=False,
        check_in_time__gte=midnight_yesterday,
        check_in_time__lt=midnight_today
    ).count()
    deliveries_yesterday = Visitor.objects.filter(
        category__name__iexact='delivery',
        check_in_time__isnull=False,
        check_in_time__gte=midnight_yesterday,
        check_in_time__lt=midnight_today
    ).count()
    
    # Calculate percentage changes
    def calculate_change(today_val, yesterday_val):
        if yesterday_val == 0:
            return 100 if today_val > 0 else 0
        return round(((today_val - yesterday_val) / yesterday_val) * 100, 1)
    
    visitors_change = calculate_change(visitors_today, visitors_yesterday)
    contractors_change = calculate_change(contractors_today, contractors_yesterday)
    deliveries_change = calculate_change(deliveries_today, deliveries_yesterday)
    
    # Pagination parameters
    page = request.GET.get('page', 1)
    per_page = int(request.GET.get('per_page', 10))  # Default to 10
    
    # Validate per_page options
    if per_page not in [10, 20, 50]:
        per_page = 10
    
    # Get active visitors (not checked out and have check_in_time)
    active_visitors_query = Visitor.objects.filter(
        check_out_time__isnull=True,
        check_in_time__isnull=False
    ).select_related('category', 'pre_registration').order_by('-check_in_time')
    
    # Get upcoming pre-registered visitors for today
    from visitors.models import PreRegistration
    upcoming_visitors_query = Visitor.objects.filter(
        is_pre_registered=True,
        check_in_time__isnull=True,
        pre_registration__expected_arrival_date=today,
        pre_registration__is_verified=False
    ).select_related('category', 'pre_registration').order_by('pre_registration__created_at')

    # New: separate counts for header chips
    active_visitors_count = active_visitors_query.count()
    upcoming_visitors_count = upcoming_visitors_query.count()
    
    # Combine queries for pagination
    from django.db.models import Q
    all_visitors_query = Visitor.objects.filter(
        Q(check_out_time__isnull=True, check_in_time__isnull=False) |
        Q(is_pre_registered=True, check_in_time__isnull=True, 
          pre_registration__expected_arrival_date=today, pre_registration__is_verified=False)
    ).select_related('category', 'pre_registration').order_by('-check_in_time')
    
    # Apply pagination
    from django.core.paginator import Paginator
    paginator = Paginator(all_visitors_query, per_page)
    
    try:
        page_obj = paginator.page(page)
    except:
        page_obj = paginator.page(1)
    
    all_visitors = page_obj.object_list
    
    # Recent check-ins (last 5) - only those with actual check_in_time
    recent_checkins = Visitor.objects.filter(
        check_in_time__isnull=False,
        check_in_time__gte=midnight_today
    ).select_related('category', 'pre_registration').order_by('-check_in_time')[:5]
    
    # Get visitor categories for the registration form
    categories = VisitorCategory.objects.filter(is_active=True)
    
    # Get site configuration for form fields
    try:
        from site_settings.models import SiteConfiguration, AddressConfiguration
        site_config = SiteConfiguration.objects.first()
        if site_config:
            form_fields = site_config.visitor_fields_config
        else:
            form_fields = {
                'full_name': {'visible': True, 'required': True},
                'ic_last_digits': {'visible': True, 'required': True},
                'contact_number': {'visible': True, 'required': True},
                'company': {'visible': True, 'required': True},
                'purpose': {'visible': True, 'required': True},
                'pass_number': {'visible': True, 'required': True},
                'vehicle_number': {'visible': True, 'required': False},
                'category': {'visible': True, 'required': True},
                'address': {'visible': False, 'required': False},
                'tower': {'visible': True, 'required': False},
                'level': {'visible': True, 'required': False},
                'unit': {'visible': True, 'required': False},
                'area_of_visit': {'visible': True, 'required': False},
            }
    except:
        form_fields = {
            'full_name': {'visible': True, 'required': True},
            'ic_last_digits': {'visible': True, 'required': True},
            'contact_number': {'visible': True, 'required': True},
            'company': {'visible': True, 'required': True},
            'purpose': {'visible': True, 'required': True},
            'pass_number': {'visible': True, 'required': True},
            'vehicle_number': {'visible': True, 'required': False},
            'category': {'visible': True, 'required': True},
            'address': {'visible': False, 'required': False},
            'tower': {'visible': True, 'required': False},
            'level': {'visible': True, 'required': False},
            'unit': {'visible': True, 'required': False},
            'area_of_visit': {'visible': True, 'required': False},
        }
    
    # Get address configuration and sort options for better UX
    address_config = AddressConfiguration.objects.first()
    if address_config:
        if address_config.tower_options:
            address_config.tower_options = sorted(address_config.tower_options, key=natural_sort_key)
        if address_config.level_options:
            address_config.level_options = sorted(address_config.level_options, key=natural_sort_key)
        if address_config.unit_options:
            address_config.unit_options = sorted(address_config.unit_options, key=natural_sort_key)
    
    # Check if using area of visit mode
    use_area_of_visit = address_config and address_config.address_mode == 'area_of_visit'
    
    # Handle visitor registration form submission
    if request.method == 'POST':
        # Extract form data based on configured fields
        form_data = {}
        required_fields = []
        
        for field_name, field_config in form_fields.items():
            if field_config.get('visible', True):
                # Skip tower/level/unit if using area_of_visit mode
                if use_area_of_visit and field_name in ('tower', 'level', 'unit'):
                    continue
                value = request.POST.get(field_name)
                form_data[field_name] = value
                if field_config.get('required', False) and not value:
                    required_fields.append(field_name.replace('_', ' ').title())
        
        # Also check area_of_visit if in area_of_visit mode
        if use_area_of_visit:
            aov_value = request.POST.get('area_of_visit')
            aov_remarks = request.POST.get('area_of_visit_remarks', '').strip()
            form_data['area_of_visit'] = aov_value
            form_data['area_of_visit_remarks'] = aov_remarks
            if not aov_value:
                required_fields.append('Area of Visit')
        
        if required_fields:
            messages.error(request, f'Please fill in all required fields: {", ".join(required_fields)}')
        else:
            try:
                # Get category if provided
                category = None
                if form_data.get('category'):
                    category = get_object_or_404(VisitorCategory, id=form_data['category'])
                
                # Create visitor with dynamic field mapping
                visitor_data = {
                    'full_name': form_data.get('full_name', ''),
                    'contact_number': form_data.get('contact_number', ''),
                    'company': form_data.get('company', ''),
                    'purpose': form_data.get('purpose', ''),
                    'vehicle_number': form_data.get('vehicle_number', ''),
                    'ic_last_digits': form_data.get('ic_last_digits', '0000'),
                    'pass_number': form_data.get('pass_number', ''),  # User-assigned pass number
                    'category': category,
                }
                
                # Add address fields if configured
                if address_config:
                    if address_config.address_mode == 'area_of_visit':
                        if form_data.get('area_of_visit'):
                            visitor_data['area_of_visit'] = form_data['area_of_visit']
                            if form_data['area_of_visit'].lower() == 'others' and form_data.get('area_of_visit_remarks'):
                                visitor_data['area_of_visit_remarks'] = form_data['area_of_visit_remarks']
                    else:
                        if address_config.enable_tower and form_data.get('tower'):
                            visitor_data['tower'] = form_data['tower']
                        if address_config.enable_level and form_data.get('level'):
                            visitor_data['level'] = form_data['level']
                        if address_config.enable_unit and form_data.get('unit'):
                            visitor_data['unit'] = form_data['unit']
                
                visitor = Visitor.objects.create(**visitor_data)
                
                # Handle plate image if provided (base64 or media URL)
                plate_image_data = request.POST.get('plate_image_data')
                plate_image_url = request.POST.get('plate_image_url')
                if plate_image_data:
                    try:
                        # Decode base64 image
                        image_data = base64.b64decode(plate_image_data)
                        image_file = ContentFile(image_data, name=f'plate_{visitor.id}_{visitor.pass_number}.jpg')
                        visitor.plate_image.save(f'plate_{visitor.id}_{visitor.pass_number}.jpg', image_file, save=True)
                    except Exception as e:
                        # Log error but don't fail registration
                        logger.error(f'Failed to save plate image for visitor {visitor.id}: {str(e)}')
                elif plate_image_url:
                    try:
                        # Convert media URL (relative or absolute) to local path and save
                        # Handles '/media/plate_images/preview_*.jpg' or 'http://host:port/media/plate_images/preview_*.jpg'
                        from urllib.parse import urlparse
                        from pathlib import Path
                        parsed = urlparse(plate_image_url)
                        rel_path = parsed.path or plate_image_url
                        # Normalize to path under MEDIA_ROOT
                        if settings.MEDIA_URL and rel_path.startswith(settings.MEDIA_URL):
                            rel_path = rel_path[len(settings.MEDIA_URL):]
                        elif '/media/' in rel_path:
                            rel_path = rel_path.split('/media/', 1)[-1]
                        src_path = Path(settings.MEDIA_ROOT) / rel_path
                        if src_path.exists():
                            with open(src_path, 'rb') as f:
                                image_file = ContentFile(f.read(), name=f'plate_{visitor.id}_{visitor.pass_number}.jpg')
                                visitor.plate_image.save(f'plate_{visitor.id}_{visitor.pass_number}.jpg', image_file, save=True)
                        else:
                            # If local file not found (e.g., served via external media server), try HTTP download.
                            try:
                                resp = requests.get(plate_image_url, timeout=5)
                                if resp.status_code == 200:
                                    visitor.plate_image.save(
                                        f'plate_{visitor.id}_{visitor.pass_number}.jpg',
                                        ContentFile(resp.content),
                                        save=True
                                    )
                                else:
                                    logger.warning(f'Plate image URL returned HTTP {resp.status_code}: {plate_image_url}')
                            except Exception as dl_err:
                                logger.error(f'HTTP download failed for plate image URL {plate_image_url}: {dl_err}')
                    except Exception as e:
                        logger.error(f'Failed to save plate image via URL for visitor {visitor.id}: {str(e)}')
                
                # Auto-whitelist vehicle plate if provided (only if ALPR whitelist is enabled)
                try:
                    if visitor.vehicle_number and visitor.vehicle_number.strip() and site_config and site_config.enable_alpr_whitelist:
                        from visitors.alpr_utils import auto_whitelist_visitor_plate
                        sync_result = auto_whitelist_visitor_plate(
                            visitor=visitor,
                            created_by=request.user,
                            expiry_hours=24
                        )
                        if sync_result.get('success'):
                            messages.success(request, f'License plate {visitor.vehicle_number} synced to camera whitelist.')
                            # Open the barrier right away when auto gate is enabled
                            if site_config.enable_auto_gate_on_checkin:
                                from visitors.alpr_utils import ALPRCameraManager
                                gate_result = ALPRCameraManager().open_gate(plate_number=visitor.vehicle_number)
                                if not gate_result.get('success'):
                                    messages.warning(request, f'Auto gate open failed: {gate_result.get("error")}')
                        else:
                            messages.warning(request, f'Whitelist sync failed: {sync_result.get("error")}')
                except Exception as e:
                    logger.error(f'Failed to sync whitelist for visitor {visitor.id}: {str(e)}')
                
                messages.success(request, f'Visitor {visitor.full_name} registered successfully with pass number {visitor.pass_number}.')
                # Auto-open visitor pass after registration
                return redirect('visitors:print_pass', visitor_id=visitor.id)
                
            except Exception as e:
                # Handle specific validation errors for pass numbers
                if 'Pass number' in str(e) and 'already in use' in str(e):
                    messages.error(request, str(e))
                else:
                    messages.error(request, f'Error registering visitor: {str(e)}')
    
    # Transform form_fields dictionary to template format
    form_fields_list = []
    field_labels = {
        'ic_last_digits': 'IC No.',
        'full_name': 'Full Name',
        'contact_number': 'Contact Number',
        'company': 'Company',
        'purpose': 'Purpose of Visit',
        'pass_number': 'Pass Number',
        'vehicle_number': 'Vehicle Number',
        'tower': 'Tower',
        'level': 'Level',
        'unit': 'Unit',
        'category': 'Category',
    }
    
    # Define field order with IC number first
    field_order = ['ic_last_digits', 'full_name', 'contact_number', 'pass_number', 'category', 'company', 'vehicle_number', 'tower', 'level', 'unit']
    
    # Check if we should show area_of_visit instead of address fields
    use_area_of_visit = address_config and address_config.address_mode == 'area_of_visit'
    
    for field_name in field_order:
        if field_name in form_fields and form_fields[field_name].get('visible', True):
            # Skip tower/level/unit if using area_of_visit mode
            if use_area_of_visit and field_name in ('tower', 'level', 'unit'):
                continue
            
            field_type = 'text'
            maxlength = None
            if field_name == 'ic_last_digits':
                field_type = 'text'  # Alphanumeric input
                maxlength = 4
            
            form_fields_list.append({
                'field_name': field_name,
                'field_label': field_labels.get(field_name, field_name.replace('_', ' ').title()),
                'is_required': form_fields[field_name].get('required', False),
                'field_type': field_type,
                'placeholder_text': f'Enter {field_labels.get(field_name, field_name.replace("_", " ")).lower()}',
                'maxlength': maxlength,
            })
    
    # Add area_of_visit field if in area_of_visit mode (before purpose)
    if use_area_of_visit:
        aov_options = list(address_config.area_of_visit_options or [])
        if 'Others' not in aov_options and 'others' not in [o.lower() for o in aov_options]:
            aov_options.append('Others')
        form_fields_list.append({
            'field_name': 'area_of_visit',
            'field_label': 'Area of Visit',
            'is_required': True,
            'field_type': 'select',
            'placeholder_text': 'Select Area',
            'options': aov_options,
            'maxlength': None,
        })
    
    # Add purpose field last
    if 'purpose' in form_fields and form_fields['purpose'].get('visible', True):
        form_fields_list.append({
            'field_name': 'purpose',
            'field_label': 'Purpose of Visit',
            'is_required': form_fields['purpose'].get('required', False),
            'field_type': 'text',
            'placeholder_text': 'Enter purpose of visit',
            'maxlength': None,
        })
    
    # Fetch Occurrence Logs and recent officer names
    occurrence_logs = OccurrenceLog.objects.select_related('created_by').all()[:100]
    recent_officer_names = [name for name in OccurrenceLog.objects.values_list('officer_name', flat=True).distinct() if name]

    context = {
        # Site information
        'site': site,
        'no_sites': site is None,
        # Analytics Cards
        'total_visitors': total_visitors,
        'total_contractors': total_contractors,
        'total_deliveries': total_deliveries,
        'overtime_visitors': overtime_visitors,
        'overtime_visitors_yesterday': overtime_visitors_yesterday,
        # Today's Stats
        'visitors_today': visitors_today,
        'contractors_today': contractors_today,
        'deliveries_today': deliveries_today,
        # Yesterday's Stats
        'visitors_yesterday': visitors_yesterday,
        'contractors_yesterday': contractors_yesterday,
        'deliveries_yesterday': deliveries_yesterday,
        # Changes
        'visitors_change': visitors_change,
        'contractors_change': contractors_change,
        'deliveries_change': deliveries_change,
        # Dynamic Category Data
        'all_categories': all_categories,
        'category_totals': category_totals,
        'category_today': category_today,
        'category_yesterday': category_yesterday,
        # Lists
        'active_visitors': all_visitors,
        'all_visitors': all_visitors,
        'recent_checkins': recent_checkins,
        'occurrence_logs': occurrence_logs,
        'recent_officer_names': recent_officer_names,
        'occurrence_categories': OccurrenceLog.CATEGORY_CHOICES,
        'occurrence_severities': OccurrenceLog.SEVERITY_CHOICES,
        # Pagination
        'page_obj': page_obj,
        'per_page': per_page,
        'total_visitors_count': paginator.count,
        # New header chip counts
        'active_visitors_count': active_visitors_count,
        'upcoming_visitors_count': upcoming_visitors_count,
        # Form data
        'categories': categories,
        'form_fields': form_fields_list,
        'address_config': address_config,
        # Door/Gate button settings
        'site_config': site_config,
    }
    
    return render(request, 'dashboard/index.html', context)


@login_required
@require_http_methods(["POST"])
def door_control_api(request):
    """
    API endpoint to control Hikvision Face Reader Terminal door access
    Endpoint: /api/door-control/
    Method: POST
    Body: {"action": "open", "door_number": 1} (door_number is optional)
    """
    try:
        # Parse request body
        data = json.loads(request.body)
        action = data.get('action')
        door_number = data.get('door_number')  # Optional override
        
        if action != 'open':
            return JsonResponse({
                'success': False,
                'message': 'Invalid action. Only "open" is supported.'
            }, status=400)
        
        # Get the current site (assuming first site for now, can be enhanced)
        try:
            site = Site.objects.filter(is_active=True).first()
            if not site:
                return JsonResponse({
                    'success': False,
                    'message': 'No active site found. Please configure your site settings.'
                }, status=500)

            # Feature flag guard: Side Door button
            cfg = SiteConfiguration.objects.filter(site=site).first()
            if cfg and not cfg.enable_side_door_button:
                return JsonResponse({
                    'success': False,
                    'message': 'Door control is disabled by administrator.'
                }, status=403)

            # Get Hikvision configuration for the site
            hikvision_config = HikvisionConfiguration.get_or_create_for_site(site)
            
            if not hikvision_config.is_enabled:
                return JsonResponse({
                    'success': False,
                    'message': 'Hikvision terminal integration is disabled. Please enable it in admin settings.'
                }, status=503)
            
            if not hikvision_config.password:
                return JsonResponse({
                    'success': False,
                    'message': 'Hikvision terminal is not configured. Please set up authentication in admin settings.'
                }, status=503)
                
        except Exception as e:
            logger.error(f"Error getting Hikvision configuration: {str(e)}")
            return JsonResponse({
                'success': False,
                'message': 'Configuration error. Please check admin settings.'
            }, status=500)
        
        # Use door number from request or default from config
        target_door = door_number if door_number is not None else hikvision_config.default_door_number
        
        # Build the endpoint URL
        endpoint_url = f"{hikvision_config.terminal_url}/ISAPI/AccessControl/RemoteControl/door/{target_door}"
        
        # Create XML body for door control
        xml_body = f'''<RemoteControlDoor version="2.0" xmlns="http://www.isapi.org/ver20/XMLSchema">
    <doorNo>{target_door}</doorNo>
    <cmd>open</cmd>
</RemoteControlDoor>'''
        
        # Set up Digest authentication
        auth = HTTPDigestAuth(hikvision_config.username, hikvision_config.password)
        
        logger.info(f"User {request.user.username} attempting to open door {target_door} via Hikvision terminal at {hikvision_config.terminal_ip}")
        
        try:
            # Make request to Hikvision terminal
            response = requests.put(
                endpoint_url,
                data=xml_body,
                auth=auth,
                timeout=hikvision_config.timeout_seconds,
                headers={
                    'Content-Type': 'application/xml',
                    'User-Agent': 'MonolithVMS/1.0'
                },
                verify=False  # Disable SSL verification for self-signed certificates
            )
            
            # Check if request was successful
            if response.status_code == 200:
                logger.info(f"Door {target_door} opened successfully by user {request.user.username}")
                return JsonResponse({
                    'success': True,
                    'message': f'Door {target_door} opened successfully',
                    'timestamp': timezone.now().isoformat(),
                    'door_number': target_door
                })
            elif response.status_code == 401:
                logger.warning(f"Authentication failed for Hikvision terminal at {hikvision_config.terminal_ip}")
                return JsonResponse({
                    'success': False,
                    'message': 'Authentication failed. Please check username and password in admin settings.'
                }, status=401)
            else:
                logger.warning(f"Hikvision terminal returned status {response.status_code}: {response.text}")
                return JsonResponse({
                    'success': False,
                    'message': f'Terminal responded with status {response.status_code}',
                    'details': response.text[:200]  # Limit response text
                }, status=502)
                
        except requests.exceptions.Timeout:
            logger.error(f"Timeout connecting to Hikvision terminal at {hikvision_config.terminal_ip}")
            return JsonResponse({
                'success': False,
                'message': f'Connection timeout after {hikvision_config.timeout_seconds} seconds. Face Reader Terminal may be offline.'
            }, status=504)
            
        except requests.exceptions.ConnectionError:
            logger.error(f"Connection error to Hikvision terminal at {hikvision_config.terminal_ip}")
            return JsonResponse({
                'success': False,
                'message': 'Cannot connect to Face Reader Terminal. Check network connection and IP address.'
            }, status=503)
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error to Hikvision terminal: {str(e)}")
            return JsonResponse({
                'success': False,
                'message': 'Network error occurred while contacting Face Reader Terminal.'
            }, status=502)
            
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid JSON in request body.'
        }, status=400)
        
    except Exception as e:
        logger.error(f"Unexpected error in door control API: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': 'An unexpected error occurred.'
        }, status=500)
        
@login_required
@require_http_methods(["POST"])
def gate_control_api(request):
    """
    API endpoint to control Dahua ANPR Camera gate access
    Endpoint: /api/gate-control/
    Method: POST
    Body: {"action": "open", "channel": 1, "plate_number": "ABC123"} (channel and plate_number optional)
    
    Uses Dahua trafficSnap.cgi openStrobe API:
    /cgi-bin/trafficSnap.cgi?action=openStrobe&channel=1&info.openType=Normal&info.plateNumber=XXX
    """
    try:
        from visitors.alpr_utils import ALPRCameraManager
        
        data = json.loads(request.body)
        action = data.get('action')
        channel = data.get('channel')
        plate_number = data.get('plate_number', 'MANUAL')
        
        if action != 'open':
            return JsonResponse({
                'success': False,
                'message': 'Invalid action. Only "open" is supported.'
            }, status=400)
        
        logger.info(f"User {request.user.username} attempting to open gate via Open Gate button")

        # Feature flag guard: Gate button
        cfg = SiteConfiguration.objects.first()
        if cfg and not cfg.enable_gate_button:
            return JsonResponse({
                'success': False,
                'message': 'Gate control is disabled by administrator.'
            }, status=403)

        camera_manager = ALPRCameraManager()
        result = camera_manager.open_gate(
            plate_number=plate_number,
            channel=channel
        )
        
        if result['success']:
            return JsonResponse({
                'success': True,
                'message': result.get('message', 'Gate opened successfully'),
                'timestamp': timezone.now().isoformat(),
                'channel': result.get('channel'),
                'plate_number': result.get('plate_number')
            })
        else:
            error_msg = result.get('error', 'Failed to open gate')
            logger.warning(f"Gate control failed: {error_msg}")
            return JsonResponse({
                'success': False,
                'message': error_msg
            }, status=503)
            
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid JSON in request body.'
        }, status=400)
        
    except Exception as e:
        logger.error(f"Unexpected error in gate control API: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': 'An unexpected error occurred.'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def add_occurrence(request):
    """Handler for recording new Daily Occurrence Book (DOB) log entries."""
    category = request.POST.get('category', 'general')
    severity = request.POST.get('severity', 'normal')
    location = request.POST.get('location', '').strip()
    title = request.POST.get('title', '').strip()
    description = request.POST.get('description', '').strip()
    
    officer_type = request.POST.get('officer_type', 'me')
    custom_officer = request.POST.get('other_officer_name', '').strip()
    
    if officer_type == 'other' and custom_officer:
        officer_name = custom_officer
    else:
        user_full_name = request.user.get_full_name().strip()
        officer_name = user_full_name if user_full_name else request.user.username

    if not title or not description:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('is_ajax') == '1':
            return JsonResponse({'success': False, 'message': 'Title and description are required.'}, status=400)
        messages.error(request, 'Title and description are required.')
        return redirect('dashboard:index')

    attachment = request.FILES.get('attachment')

    occurrence = OccurrenceLog.objects.create(
        category=category,
        severity=severity,
        location=location,
        title=title,
        description=description,
        attachment=attachment,
        created_by=request.user,
        officer_name=officer_name,
    )

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('is_ajax') == '1':
        return JsonResponse({
            'success': True,
            'message': 'Occurrence log added successfully.',
            'occurrence': {
                'id': occurrence.id,
                'category': occurrence.get_category_display(),
                'severity': occurrence.severity,
                'location': occurrence.location or '-',
                'title': occurrence.title,
                'description': occurrence.description,
                'officer_name': occurrence.officer_name,
                'created_at': timezone.localtime(occurrence.created_at).strftime('%Y-%m-%d %H:%M'),
                'attachment_url': occurrence.attachment.url if occurrence.attachment else None
            }
        })

    messages.success(request, f'Occurrence entry "{title}" logged successfully by {officer_name}.')
    return redirect('dashboard:index')


@login_required
def get_recent_officers_api(request):
    """API endpoint to retrieve distinct officer names recorded previously for autocomplete."""
    officers = [name for name in OccurrenceLog.objects.values_list('officer_name', flat=True).distinct() if name]
    return JsonResponse({'officers': officers})

