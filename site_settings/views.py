from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, FileResponse, Http404, JsonResponse
from django.contrib import messages
from django.core.management import call_command
from .models import Site, SiteConfiguration, VisitorCategory
from .forms import SiteForm
from accounts.decorators import admin_required
from django.conf import settings
import os
# Add imports for restore
from django.db import transaction, models
from visitors.models import Visitor, ALPRWhitelist
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.core.paginator import Paginator
import json

@login_required
@admin_required
def site_configuration(request):
    """Single site configuration view"""
    # Get or create the single site
    site = Site.objects.first()
    if not site:
        # Create default site if none exists
        site = Site.objects.create(
            name='My VMS Site',
            address='',
            postal_code='',
            contact_number='',
            email='admin@example.com'
        )
        # Create default logo
        SiteLogo.objects.create(site=site)
        
        # Create default configuration
        SiteConfiguration.objects.create(
            site=site,
            language='en',
            enable_pre_registration=True,
            enable_qr_code=True,
            enable_otp=True,
                visitor_fields_config={
                    'ic_last_digits': {'required': True, 'visible': True},
                    'full_name': {'required': True, 'visible': True},
                    'contact_number': {'required': True, 'visible': True},
                    'company': {'required': True, 'visible': True},
                    'purpose': {'required': True, 'visible': True},
                    'pass_number': {'required': True, 'visible': True},
                    'vehicle_number': {'required': False, 'visible': True},
                    'category': {'required': False, 'visible': True},
                    'tower': {'required': False, 'visible': True},
                    'level': {'required': False, 'visible': True},
                    'unit': {'required': False, 'visible': True},
                    'area_of_visit': {'required': False, 'visible': True},
                }
        )
    
    # Get or create site logo
    try:
        site_logo = site.logo
    except SiteLogo.DoesNotExist:
        site_logo = SiteLogo.objects.create(site=site)
    
    if request.method == 'POST':
        # Handle logo uploads
        if 'logo_light' in request.FILES:
            site_logo.logo_light = request.FILES['logo_light']
            site_logo.save()
            messages.success(request, 'Light theme logo updated successfully!')
        
        if 'logo_dark' in request.FILES:
            site_logo.logo_dark = request.FILES['logo_dark']
            site_logo.save()
            messages.success(request, 'Dark theme logo updated successfully!')
        
        # Handle site information update
        if 'name' in request.POST and not any(key in request.FILES for key in ['logo_light', 'logo_dark']):
            site.name = request.POST.get('name', site.name)
            site.address = request.POST.get('address', site.address)
            site.postal_code = request.POST.get('postal_code', site.postal_code)
            site.contact_number = request.POST.get('contact_number', site.contact_number)
            site.email = request.POST.get('email', site.email)
            site.save()
            messages.success(request, 'Site configuration updated successfully!')
        
        return redirect('site_settings:site_configuration')
    
    context = {
        'site': site,
        'site_logo': site_logo,
    }
    return render(request, 'site_settings/site_configuration.html', context)

@login_required
@admin_required
def site_list(request):
    # Redirect to single site configuration
    return redirect('site_settings:site_configuration')

@login_required
@admin_required
def site_add(request):
    if request.method == 'POST':
        form = SiteForm(request.POST)
        if form.is_valid():
            site = form.save()
            
            # Create default configuration
            SiteConfiguration.objects.create(
                site=site,
                language='en',
                enable_pre_registration=True,
                enable_qr_code=True,
                enable_otp=True,
                visitor_fields_config={
                    'ic_last_digits': {'required': True, 'visible': True},
                    'full_name': {'required': True, 'visible': True},
                    'contact_number': {'required': True, 'visible': True},
                    'company': {'required': True, 'visible': True},
                    'purpose': {'required': True, 'visible': True},
                    'pass_number': {'required': True, 'visible': True},
                    'vehicle_number': {'required': False, 'visible': True},
                    'category': {'required': False, 'visible': True},
                    'tower': {'required': False, 'visible': True},
                    'level': {'required': False, 'visible': True},
                    'unit': {'required': False, 'visible': True},
                }
            )
            
            messages.success(request, f"Site '{site.name}' has been created successfully")
            return redirect('site_settings:site_list')
    else:
        form = SiteForm()
    
    return render(request, 'site_settings/site_form.html', {'form': form})

@login_required
@admin_required
def site_edit(request, site_id):
    site = get_object_or_404(Site, id=site_id)
    config = site.configuration
    
    if request.method == 'POST':
        site.name = request.POST.get('name')
        site.address = request.POST.get('address')
        site.contact_person = request.POST.get('contact_person')
        site.contact_email = request.POST.get('contact_email')
        site.contact_phone = request.POST.get('contact_phone')
        
        if 'logo' in request.FILES:
            site.logo = request.FILES.get('logo')
        
        site.save()
        
        # Update configuration
        config.language = request.POST.get('language', 'en')
        config.enable_pre_registration = 'enable_pre_registration' in request.POST
        config.enable_qr_code = 'enable_qr_code' in request.POST
        config.enable_otp = 'enable_otp' in request.POST
        
        # Update visitor fields configuration
        visitor_fields = ['full_name', 'email', 'phone', 'company', 'purpose', 
                         'pass_number', 'vehicle_number', 'address']
        
        visitor_fields_config = {}
        for field in visitor_fields:
            visitor_fields_config[field] = {
                'required': f'{field}_required' in request.POST,
                'visible': f'{field}_visible' in request.POST
            }
        
        config.visitor_fields_config = visitor_fields_config
        config.save()
        
        messages.success(request, f"Site '{site.name}' has been updated successfully")
        return redirect('site_settings:site_list')
    
    context = {
        'site': site,
        'config': config
    }
    
    return render(request, 'site_settings/site_form.html', context)

@login_required
@admin_required
def category_list(request):
    categories = VisitorCategory.objects.all().select_related('site')
    return render(request, 'site_settings/category_list.html', {'categories': categories})

@login_required
@admin_required
def category_add(request):
    sites = Site.objects.all()
    
    if request.method == 'POST':
        name = request.POST.get('name')
        site_id = request.POST.get('site')
        color_code = request.POST.get('color_code', '#3498db')
        
        site = get_object_or_404(Site, id=site_id)
        
        VisitorCategory.objects.create(
            name=name,
            site=site,
            color_code=color_code
        )
        
        messages.success(request, f"Category '{name}' has been created successfully")
        return redirect('site_settings:category_list')
    
    context = {
        'sites': sites
    }
    
    return render(request, 'site_settings/category_form.html', context)

@login_required
@admin_required
def settings_dashboard(request):
    """Main settings dashboard with navigation to different settings sections"""
    sites_count = Site.objects.count()
    categories_count = VisitorCategory.objects.count()
    # Provide site configuration for feature-flagged UI
    site = Site.objects.first()
    site_config = None
    if site:
        try:
            site_config, _ = SiteConfiguration.objects.get_or_create(site=site)
        except Exception:
            site_config = None
    
    context = {
        'sites_count': sites_count,
        'categories_count': categories_count,
        'site_config': site_config,
        'site': site,
    }
    return render(request, 'site_settings/settings_dashboard.html', context)

@login_required
@admin_required
def site_delete(request, site_id):
    """Delete a site"""
    site = get_object_or_404(Site, id=site_id)
    
    if request.method == 'POST':
        site_name = site.name
        site.delete()
        messages.success(request, f"Site '{site_name}' has been deleted successfully")
        return redirect('site_settings:site_list')
    
    return render(request, 'site_settings/site_confirm_delete.html', {'site': site})

@login_required
@admin_required
def category_delete(request, category_id):
    """Delete a category"""
    category = get_object_or_404(VisitorCategory, id=category_id)
    
    if request.method == 'POST':
        category_name = category.name
        category.delete()
        messages.success(request, f"Category '{category_name}' has been deleted successfully")
        return redirect('site_settings:category_list')
    
    return render(request, 'site_settings/category_confirm_delete.html', {'category': category})

@login_required
def form_fields_management(request):
    """Manage form field configurations"""
    sites = Site.objects.all()
    
    # Get the first site's configuration or create default
    if sites.exists():
        site = sites.first()
        try:
            config = SiteConfiguration.objects.get(site=site)
        except SiteConfiguration.DoesNotExist:
            # Create default configuration
            config = SiteConfiguration.objects.create(
                site=site,
                language='en',
                enable_pre_registration=True,
                enable_qr_code=True,
                enable_otp=True,
                visitor_fields_config={
                    'ic_last_digits': {'required': True, 'visible': True},
                    'full_name': {'required': True, 'visible': True},
                    'contact_number': {'required': True, 'visible': True},
                    'company': {'required': True, 'visible': True},
                    'purpose': {'required': True, 'visible': True},
                    'pass_number': {'required': True, 'visible': True},
                    'vehicle_number': {'required': False, 'visible': True},
                    'category': {'required': False, 'visible': True},
                    'tower': {'required': False, 'visible': True},
                    'level': {'required': False, 'visible': True},
                    'unit': {'required': False, 'visible': True},
                }
            )
    else:
        config = None
    
    # Get categories and address configuration
    from .models import VisitorCategory, AddressConfiguration
    categories = VisitorCategory.objects.all()
    address_config = AddressConfiguration.objects.first()
    
    context = {
        'sites': sites,
        'config': config,
        'selected_site': site if sites.exists() else None,
        'categories': categories,
        'address_config': address_config,
    }
    
    return render(request, 'site_settings/form_fields_management.html', context)

@login_required
def update_form_fields(request):
    """Update form field configurations"""
    if request.method == 'POST':
        # Get the first site (single site deployment)
        site = Site.objects.first()
        if not site:
            messages.error(request, 'No site found. Please create a site first.')
            return redirect('site_settings:form_fields_management')
        
        try:
            config = SiteConfiguration.objects.get(site=site)
        except SiteConfiguration.DoesNotExist:
            config = SiteConfiguration.objects.create(site=site)
        
        # Update field configurations
        field_config = {}
        fields = ['ic_last_digits', 'full_name', 'contact_number', 'company', 'purpose', 'pass_number', 
                 'vehicle_number', 'category', 'address', 'tower', 'level', 'unit']
        
        for field in fields:
            field_config[field] = {
                'visible': f'{field}_visible' in request.POST,
                'required': f'{field}_required' in request.POST,
            }
        
        config.visitor_fields_config = field_config
        
        # Update other settings
        config.enable_pre_registration = 'enable_pre_registration' in request.POST
        config.enable_qr_code = 'enable_qr_code' in request.POST
        config.enable_otp = 'enable_otp' in request.POST
        config.enable_printer = 'enable_printer' in request.POST
        
        config.save()
        
        messages.success(request, 'Form field configuration updated successfully')
        return redirect('site_settings:form_fields_management')
    
    return redirect('site_settings:form_fields_management')

@login_required
def update_address_options(request):
    """Update address field options via AJAX"""
    if request.method == 'POST':
        import json
        from django.http import JsonResponse
        from .models import AddressConfiguration
        
        try:
            data = json.loads(request.body)
            action = data.get('action')
            field_type = data.get('field_type')
            value = data.get('value')
            
            if not all([action, field_type, value]):
                return JsonResponse({'success': False, 'error': 'Missing required parameters'})
            
            # Get or create address configuration
            address_config, created = AddressConfiguration.objects.get_or_create(
                defaults={
                    'enable_tower': True,
                    'enable_level': True,
                    'enable_unit': True,
                    'tower_label': 'Tower',
                    'level_label': 'Level',
                    'unit_label': 'Unit',
                    'tower_options': [],
                    'level_options': [],
                    'unit_options': [],
                    'address_mode': 'address_fields',
                    'area_of_visit_options': [],
                }
            )
            
            # Handle mode toggle (no value needed for set_mode)
            if action == 'set_mode':
                mode = data.get('mode')
                if mode in ('address_fields', 'area_of_visit'):
                    address_config.address_mode = mode
                    address_config.save()
                    return JsonResponse({'success': True})
                else:
                    return JsonResponse({'success': False, 'error': 'Invalid mode'})
            
            if not value:
                return JsonResponse({'success': False, 'error': 'Missing required parameters'})
            
            # Handle area_of_visit options
            if field_type == 'area_of_visit':
                current_options = address_config.area_of_visit_options
            else:
                # Get the current options for the field type (tower/level/unit)
                field_options_attr = f'{field_type}_options'
                current_options = getattr(address_config, field_options_attr, [])
            
            if action == 'add':
                if value not in current_options:
                    current_options.append(value)
                    if field_type == 'area_of_visit':
                        address_config.area_of_visit_options = current_options
                    else:
                        setattr(address_config, field_options_attr, current_options)
                    address_config.save()
                    return JsonResponse({'success': True})
                else:
                    return JsonResponse({'success': False, 'error': 'Option already exists'})
            
            elif action == 'remove':
                if value in current_options:
                    current_options.remove(value)
                    if field_type == 'area_of_visit':
                        address_config.area_of_visit_options = current_options
                    else:
                        setattr(address_config, field_options_attr, current_options)
                    address_config.save()
                    return JsonResponse({'success': True})
                else:
                    return JsonResponse({'success': False, 'error': 'Option not found'})
            
            else:
                return JsonResponse({'success': False, 'error': 'Invalid action'})
                
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@login_required
@admin_required
def category_edit(request, category_id):
    category = get_object_or_404(VisitorCategory, id=category_id)
    sites = Site.objects.all()
    
    if request.method == 'POST':
        category.name = request.POST.get('name')
        site_id = request.POST.get('site')
        category.site = get_object_or_404(Site, id=site_id)
        category.color_code = request.POST.get('color_code', '#3498db')
        category.save()
        
        messages.success(request, f"Category '{category.name}' has been updated successfully")
        return redirect('site_settings:category_list')
    
    context = {
        'category': category,
        'sites': sites
    }
    
    return render(request, 'site_settings/category_form.html', context)

@login_required
@admin_required
def backup_settings(request):
    """Admin-only Auto Backup & Recovery settings page"""
    # Single-site assumption per existing patterns
    site = Site.objects.first()
    if not site:
        messages.error(request, "No site found. Please create a site first.")
        return redirect('site_settings:site_list')

    # Ensure configuration exists
    config, _ = SiteConfiguration.objects.get_or_create(site=site)

    if request.method == 'POST':
        # Restore flow
        if 'restore' in request.POST:
            data = None
            quick_name = request.POST.get('quick_file_name')
            if quick_name:
                out_dir = config.backup_output_dir or 'backups'
                # Basic security checks: no separators, correct prefix/suffix
                if ('/' in quick_name) or ('\\' in quick_name) or not quick_name.startswith(f'site_{site.id}_') or not quick_name.endswith('.json'):
                    messages.error(request, 'Invalid backup file name.')
                    return redirect('site_settings:backup_settings')
                fpath = os.path.join(out_dir, quick_name)
                if not os.path.isfile(fpath):
                    messages.error(request, 'Selected backup file was not found on the server.')
                    return redirect('site_settings:backup_settings')
                try:
                    with open(fpath, 'r', encoding='utf-8') as fh:
                        data = json.load(fh)
                except Exception as e:
                    messages.error(request, f'Failed to read backup file: {e}')
                    return redirect('site_settings:backup_settings')
            else:
                upload = request.FILES.get('restore_file')
                if not upload:
                    messages.error(request, 'Please choose a backup JSON file to restore.')
                    return redirect('site_settings:backup_settings')
                try:
                    data = json.load(upload)
                except Exception as e:
                    messages.error(request, f'Invalid JSON file: {e}')
                    return redirect('site_settings:backup_settings')

            clear = 'clear_before_restore' in request.POST
            restored_count = 0
            skipped_count = 0
            created_categories = 0
            try:
                with transaction.atomic():
                    if clear:
                        # Delete existing visitors for this site, then categories
                        Visitor.objects.filter(category__site=site).delete()
                        VisitorCategory.objects.filter(site=site).delete()
                    # Build categories mapping from old pk -> new instance
                    old_to_new_cat = {}
                    for entry in (data.get('categories', []) or []):
                        fields = entry.get('fields', {})
                        name = fields.get('name')
                        if not name:
                            continue
                        is_active = fields.get('is_active', True)
                        cat, created = VisitorCategory.objects.get_or_create(
                            site=site,
                            name=name,
                            defaults={'is_active': is_active}
                        )
                        if not created:
                            # Update active flag to match backup
                            if cat.is_active != is_active:
                                cat.is_active = is_active
                                cat.save(update_fields=['is_active'])
                        else:
                            created_categories += 1
                        old_to_new_cat[entry.get('pk')] = cat

                    # Restore visitors
                    for entry in (data.get('visitors', []) or []):
                        fields = entry.get('fields', {})
                        pass_number = fields.get('pass_number')
                        old_cat_pk = fields.get('category')
                        category = old_to_new_cat.get(old_cat_pk) if old_cat_pk else None

                        check_in = parse_datetime(fields.get('check_in_time')) if fields.get('check_in_time') else None
                        check_out = parse_datetime(fields.get('check_out_time')) if fields.get('check_out_time') else None

                        defaults = {
                            'category': category,
                            'ic_last_digits': fields.get('ic_last_digits') or '',
                            'full_name': fields.get('full_name') or '',
                            'contact_number': fields.get('contact_number') or '',
                            'vehicle_number': fields.get('vehicle_number'),
                            'company': fields.get('company'),
                            'tower': fields.get('tower'),
                            'level': fields.get('level'),
                            'unit': fields.get('unit'),
                            'area_of_visit': fields.get('area_of_visit'),
                            'purpose': fields.get('purpose'),
                            'check_in_time': check_in,
                            'check_out_time': check_out,
                            'is_pre_registered': fields.get('is_pre_registered', False),
                        }
                        try:
                            if pass_number:
                                # Update existing or create new by pass_number
                                obj, created = Visitor.objects.update_or_create(
                                    pass_number=pass_number,
                                    defaults=defaults
                                )
                                restored_count += 1
                            else:
                                Visitor.objects.create(**defaults)
                                restored_count += 1
                        except Exception:
                            skipped_count += 1
                    
                    # Restore address configuration if present in backup
                    addr_data = data.get('address_configuration')
                    if addr_data:
                        from .models import AddressConfiguration
                        addr_config, _ = AddressConfiguration.objects.get_or_create(site=site)
                        addr_config.address_mode = addr_data.get('address_mode', 'address_fields')
                        addr_config.enable_tower = addr_data.get('enable_tower', True)
                        addr_config.tower_options = addr_data.get('tower_options', [])
                        addr_config.enable_level = addr_data.get('enable_level', True)
                        addr_config.level_options = addr_data.get('level_options', [])
                        addr_config.enable_unit = addr_data.get('enable_unit', True)
                        addr_config.unit_options = addr_data.get('unit_options', [])
                        addr_config.area_of_visit_options = addr_data.get('area_of_visit_options', [])
                        addr_config.save()
                
                messages.success(
                    request,
                    f"Restore completed. Visitors restored: {restored_count}. Skipped: {skipped_count}. Categories created: {created_categories}."
                )
            except Exception as e:
                messages.error(request, f'Restore failed: {e}')
            return redirect('site_settings:backup_settings')

        if 'run_now' in request.POST:
            # Run backup immediately using management command
            output_dir = request.POST.get('backup_output_dir', config.backup_output_dir or 'backups')
            try:
                os.makedirs(output_dir, exist_ok=True)
                call_command('backup_site', site_id=site.id, output_dir=output_dir)
                messages.success(request, f"Backup started for '{site.name}'. Check the '{output_dir}' folder for results.")
            except Exception as e:
                messages.error(request, f"Failed to run backup: {e}")
            return redirect('site_settings:backup_settings')
        else:
            # Save settings
            config.enable_auto_backup = 'enable_auto_backup' in request.POST
            config.backup_output_dir = request.POST.get('backup_output_dir') or 'backups'
            config.backup_frequency = request.POST.get('backup_frequency') or 'daily'
            config.backup_keep_days = int(request.POST.get('backup_keep_days') or 30)
            # time input: HH:MM
            time_val = request.POST.get('backup_time') or '02:00'
            try:
                from datetime import datetime
                config.backup_time = datetime.strptime(time_val, '%H:%M').time()
            except Exception:
                messages.warning(request, "Invalid time format. Using 02:00.")
                from datetime import time as dtime
                config.backup_time = dtime(2, 0)
            config.save()
            messages.success(request, 'Backup settings saved successfully.')
            return redirect('site_settings:backup_settings')

    # List existing backups for convenience
    existing_backups = []
    try:
        out_dir = config.backup_output_dir or 'backups'
        if os.path.isdir(out_dir):
            files = [f for f in os.listdir(out_dir) if f.startswith(f'site_{site.id}_') and f.endswith('.json')]
            files.sort(key=lambda fn: os.path.getmtime(os.path.join(out_dir, fn)), reverse=True)
            existing_backups = files[:10]
    except Exception:
        existing_backups = []

    context = {
        'site': site,
        'config': config,
        'BASE_DIR': settings.BASE_DIR,
        'existing_backups': existing_backups,
    }

    return render(request, 'site_settings/backup_settings.html', context)


@login_required
@admin_required
def download_backup(request):
    """Securely download a backup JSON file for the current site."""
    site = Site.objects.first()
    if not site:
        raise Http404("Site not found")
    config, _ = SiteConfiguration.objects.get_or_create(site=site)
    name = request.GET.get('name')
    if not name:
        raise Http404("Missing file name")
    # Prevent path traversal and cross-site access
    if ('/' in name) or ('\\' in name) or not name.startswith(f'site_{site.id}_') or not name.endswith('.json'):
        raise Http404("Invalid file name")
    out_dir = config.backup_output_dir or 'backups'
    fpath = os.path.join(out_dir, name)
    if not os.path.isfile(fpath):
        raise Http404("File not found")
    return FileResponse(open(fpath, 'rb'), as_attachment=True, filename=name, content_type='application/json')


@login_required
@admin_required
def alpr_whitelist(request):
    """ALPR Whitelist management view"""
    # Feature flag guard: block access when ALPR whitelist disabled
    site = Site.objects.first()
    config = None
    if site:
        try:
            config, _ = SiteConfiguration.objects.get_or_create(site=site)
        except Exception:
            config = None
    if config and not getattr(config, 'enable_alpr_whitelist', False):
        messages.error(request, 'ALPR Whitelist feature is disabled by administrator.')
        return redirect('site_settings:settings_dashboard')
    # Handle POST requests for adding/updating whitelist entries
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'add':
            visitor_id = request.POST.get('visitor_id')
            plate_number = request.POST.get('plate_number')
            expires_at = request.POST.get('expires_at')
            
            if visitor_id and plate_number and expires_at:
                try:
                    visitor = Visitor.objects.get(id=visitor_id)
                    expires_datetime = timezone.datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                    
                    whitelist_entry, created = ALPRWhitelist.objects.get_or_create(
                        visitor=visitor,
                        plate_number=plate_number.upper().replace(' ', ''),
                        defaults={
                            'expires_at': expires_datetime,
                            'created_by': request.user,
                            'is_active': True
                        }
                    )
                    
                    if created:
                        messages.success(request, f'License plate {plate_number} has been added to the whitelist.')
                    else:
                        # Update existing entry
                        whitelist_entry.expires_at = expires_datetime
                        whitelist_entry.is_active = True
                        whitelist_entry.save()
                        messages.info(request, f'License plate {plate_number} whitelist has been updated.')
                        
                except Visitor.DoesNotExist:
                    messages.error(request, 'Selected visitor not found.')
                except Exception as e:
                    messages.error(request, f'Error adding to whitelist: {str(e)}')
            else:
                messages.error(request, 'All fields are required.')
                
        elif action == 'toggle_status':
            whitelist_id = request.POST.get('whitelist_id')
            try:
                whitelist_entry = ALPRWhitelist.objects.get(id=whitelist_id)
                whitelist_entry.is_active = not whitelist_entry.is_active
                whitelist_entry.save()
                status = 'activated' if whitelist_entry.is_active else 'deactivated'
                messages.success(request, f'Whitelist entry has been {status}.')
            except ALPRWhitelist.DoesNotExist:
                messages.error(request, 'Whitelist entry not found.')
                
        elif action == 'delete':
            whitelist_id = request.POST.get('whitelist_id')
            try:
                whitelist_entry = ALPRWhitelist.objects.get(id=whitelist_id)
                plate_number = whitelist_entry.plate_number
                whitelist_entry.delete()
                messages.success(request, f'License plate {plate_number} has been removed from the whitelist.')
            except ALPRWhitelist.DoesNotExist:
                messages.error(request, 'Whitelist entry not found.')
        
        return redirect('site_settings:alpr_whitelist')
    
    # Handle GET requests - display whitelist
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', 'all')
    
    # Get whitelist entries
    whitelist_entries = ALPRWhitelist.objects.select_related('visitor', 'created_by').all()
    
    # Apply search filter
    if search_query:
        whitelist_entries = whitelist_entries.filter(
            models.Q(plate_number__icontains=search_query) |
            models.Q(visitor__full_name__icontains=search_query) |
            models.Q(visitor__company__icontains=search_query)
        )
    
    # Apply status filter
    if status_filter == 'active':
        whitelist_entries = whitelist_entries.filter(is_active=True)
    elif status_filter == 'inactive':
        whitelist_entries = whitelist_entries.filter(is_active=False)
    elif status_filter == 'expired':
        whitelist_entries = whitelist_entries.filter(expires_at__lt=timezone.now())
    elif status_filter == 'synced':
        whitelist_entries = whitelist_entries.filter(synced_to_camera=True)
    elif status_filter == 'unsynced':
        whitelist_entries = whitelist_entries.filter(synced_to_camera=False)
    
    # Pagination
    paginator = Paginator(whitelist_entries, 25)  # Show 25 entries per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get recent visitors for the add form
    recent_visitors = Visitor.objects.filter(
        check_in_time__isnull=False
    ).order_by('-check_in_time')[:50]
    
    # Statistics
    total_entries = ALPRWhitelist.objects.count()
    active_entries = ALPRWhitelist.objects.filter(is_active=True).count()
    expired_entries = ALPRWhitelist.objects.filter(expires_at__lt=timezone.now()).count()
    synced_entries = ALPRWhitelist.objects.filter(synced_to_camera=True).count()
    
    context = {
        'page_obj': page_obj,
        'recent_visitors': recent_visitors,
        'search_query': search_query,
        'status_filter': status_filter,
        'stats': {
            'total': total_entries,
            'active': active_entries,
            'expired': expired_entries,
            'synced': synced_entries,
            'unsynced': total_entries - synced_entries,
        }
    }
    
    return render(request, 'site_settings/alpr_whitelist.html', context)
