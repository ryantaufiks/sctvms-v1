from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db.models import Q, Count
from datetime import datetime, timedelta
import csv
import json
from io import BytesIO

from visitors.models import Visitor, PreRegistration, ALPRWhitelist
from residents.models import ResidentVehicleLog, Resident, ResidentVehicle
from site_settings.models import Site, VisitorCategory
from accounts.decorators import can_view_reports
from accounts.models import ActivityLog
from django.contrib.auth.models import User
from django.contrib import messages
from django.core.paginator import Paginator

# Install required packages for Excel and PDF export
try:
    import openpyxl
    from openpyxl.styles import Font, Alignment
except ImportError:
    openpyxl = None

# Import core ReportLab components first; keep charts optional so PDF doesn't fail if a chart module is missing
try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import inch
except ImportError:
    SimpleDocTemplate = None

# Optional utilities and charts (fail gracefully if unavailable)
try:
    from reportlab.lib.utils import ImageReader
except Exception:
    ImageReader = None
try:
    from reportlab.graphics.shapes import Drawing
except Exception:
    Drawing = None
try:
    from reportlab.graphics.charts.barcharts import VerticalBarChart
except Exception:
    VerticalBarChart = None
try:
    from reportlab.graphics.charts.piecharts import Pie
except Exception:
    Pie = None

@login_required
def reports_dashboard(request):
    """Main reports dashboard"""
    user_profile = request.user.profile
    
    # Single site deployment - get all active sites
    sites = Site.objects.filter(is_active=True)
    
    context = {
        'sites': sites,
        'user_role': user_profile.role,
    }
    
    return render(request, 'reports/dashboard.html', context)

@login_required
def visitor_report(request):
    """Generate consolidated visitor reports with smart search and filters"""
    user_profile = request.user.profile
    export_format = (request.GET.get('export') or '').strip().lower()
    
    # Get available sites (single site deployment)
    sites = Site.objects.filter(is_active=True)
    
    # Get filter parameters
    category_id = request.GET.get('category')  # Form uses 'category' name
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    status = request.GET.get('status')  # active, checked_out, all
    search = request.GET.get('search')
    sort_by = request.GET.get('sort', '-check_in_time')
    page = request.GET.get('page', 1)
    
    # Build query - show all visitors for single site deployment
    visitors = Visitor.objects.all()
    
    # Apply filters
    if category_id:
        visitors = visitors.filter(category_id=category_id)
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            visitors = visitors.filter(check_in_time__date__gte=date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            visitors = visitors.filter(check_in_time__date__lte=date_to_obj)
        except ValueError:
            pass
    
    if status == 'active':
        visitors = visitors.filter(check_out_time__isnull=True)
    elif status == 'checked_out':
        visitors = visitors.filter(check_out_time__isnull=False)
    
    # Enhanced smart search
    if search:
        visitors = visitors.filter(
            Q(full_name__icontains=search) |
            Q(company__icontains=search) |
            Q(contact_number__icontains=search) |
            Q(pass_number__icontains=search) |
            Q(purpose__icontains=search) |
            Q(ic_last_digits__icontains=search) |
            Q(vehicle_number__icontains=search) |
            Q(category__name__icontains=search)
        )
    
    # Apply sorting
    valid_sort_fields = [
        'check_in_time', '-check_in_time',
        'full_name', '-full_name',
        'company', '-company',
        'category__name', '-category__name',
        'check_out_time', '-check_out_time'
    ]
    
    if sort_by in valid_sort_fields:
        visitors = visitors.order_by(sort_by)
    else:
        visitors = visitors.order_by('-check_in_time')
    
    visitors = visitors.select_related('category')
    
    # Get total count before pagination
    total_count = visitors.count()
    
    # Handle export requests
    if export_format in {'csv', 'excel', 'pdf'}:
        return export_visitor_data(visitors, export_format, request)
    
    # Pagination
    from django.core.paginator import Paginator
    paginator = Paginator(visitors, 50)  # Show 50 visitors per page
    
    try:
        page_obj = paginator.page(page)
    except:
        page_obj = paginator.page(1)
    
    # Get categories for the filter (single site deployment)
    categories = VisitorCategory.objects.filter(is_active=True)
    
    context = {
        'visitors': page_obj.object_list,
        'page_obj': page_obj,
        'sites': sites,
        'categories': categories,
        'filters': {
            'category': category_id or '',
            'date_from': date_from or '',
            'date_to': date_to or '',
            'status': status or '',
            'search': search or '',
            'sort': sort_by or '',
        },
        'total_count': total_count,
    }
    
    return render(request, 'reports/visitor_report.html', context)

def export_visitor_data(visitors, format_type, request):
    """Export visitor data in various formats"""
    filename = f'visitor_report_{timezone.now().strftime("%Y%m%d_%H%M%S")}'
    fmt = (format_type or '').strip().lower()
    
    # Helper: safely return file URL if the image/file exists
    def _safe_file_url(fieldfile):
        try:
            if fieldfile and getattr(fieldfile, 'name', None):
                return fieldfile.url
        except Exception:
            # Covers ValueError: no file associated, and any storage URL error
            return ''
        return ''
    
    if fmt == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'Full Name', 'Contact Number', 'Company', 'Category', 
            'Check-in Time', 'Check-out Time', 'Pass Number', 'Vehicle Number',
            'Tower', 'Level', 'Unit', 'Purpose', 'IC Last Digits', 'Status', 'Duration'
        ])
        
        for visitor in visitors:
            duration = ''
            if visitor.check_out_time:
                duration = str(visitor.check_out_time - visitor.check_in_time)
            else:
                duration = str(timezone.now() - visitor.check_in_time)
            
            writer.writerow([
                visitor.full_name,
                visitor.contact_number,
                visitor.company or '',
                visitor.category.name if visitor.category else '',
                visitor.check_in_time.strftime('%Y-%m-%d %H:%M:%S'),
                visitor.check_out_time.strftime('%Y-%m-%d %H:%M:%S') if visitor.check_out_time else '',
                visitor.pass_number or '',
                visitor.vehicle_number or '',
                visitor.tower or '',
                visitor.level or '',
                visitor.unit or '',
                visitor.purpose or '',
                visitor.ic_last_digits or '',
                'Checked Out' if visitor.check_out_time else 'Active',
                duration
            ])
        
        return response
    
    elif fmt == 'excel' and openpyxl:
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="{filename}.xlsx"'
        
        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.title = 'Visitor Report'
        
        # Header
        headers = [
            'Full Name', 'Contact Number', 'Company', 'Category', 
            'Check-in Time', 'Check-out Time', 'Pass Number', 'Vehicle Number',
            'Tower', 'Level', 'Unit', 'Purpose', 'IC Last Digits', 'Status', 'Duration'
        ]
        
        for col, header in enumerate(headers, 1):
            cell = worksheet.cell(row=1, column=col, value=header)
            cell.font = Font(bold=True)
        
        # Data rows
        for row, visitor in enumerate(visitors, 2):
            duration = ''
            if visitor.check_out_time:
                duration = str(visitor.check_out_time - visitor.check_in_time)
            else:
                duration = str(timezone.now() - visitor.check_in_time)
            
            data = [
                visitor.full_name,
                visitor.contact_number,
                visitor.company or '',
                visitor.category.name if visitor.category else '',
                visitor.check_in_time.strftime('%Y-%m-%d %H:%M:%S'),
                visitor.check_out_time.strftime('%Y-%m-%d %H:%M:%S') if visitor.check_out_time else '',
                visitor.pass_number or '',
                visitor.vehicle_number or '',
                visitor.tower or '',
                visitor.level or '',
                visitor.unit or '',
                visitor.purpose or '',
                visitor.ic_last_digits or '',
                'Checked Out' if visitor.check_out_time else 'Active',
                duration
            ]
            
            for col, value in enumerate(data, 1):
                worksheet.cell(row=row, column=col, value=value)
        
        workbook.save(response)
        return response
    
    elif fmt == 'pdf' and SimpleDocTemplate:
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}.pdf"'
        
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=48,
            rightMargin=48,
            topMargin=60,
            bottomMargin=54,
        )
        
        # Container for the 'Flowable' objects
        elements = []
        
        # Resolve site and date range for header and analytics
        primary_site = Site.objects.filter(is_active=True).first()
        date_from = request.GET.get('date_from') or ''
        date_to = request.GET.get('date_to') or ''
        
        # Build analytics from the provided visitors queryset
        try:
            total_visitors = visitors.count()
            active_visitors = visitors.filter(check_out_time__isnull=True).count()
            checked_out_visitors = total_visitors - active_visitors
            total_hours = 0.0
            for v in visitors:
                end_time = v.check_out_time or timezone.now()
                total_hours += max(0.0, (end_time - v.check_in_time).total_seconds() / 3600.0)
            avg_duration_hours = round((total_hours / total_visitors), 1) if total_visitors else 0.0
            # Daily visitors
            dv_counter = {}
            for v in visitors:
                d = v.check_in_time.date().isoformat()
                dv_counter[d] = dv_counter.get(d, 0) + 1
            daily_visitors = [{'date': d, 'count': c} for d, c in sorted(dv_counter.items())]
            # Category distribution
            cat_counter = {}
            for v in visitors:
                name = v.category.name if v.category else 'Uncategorized'
                cat_counter[name] = cat_counter.get(name, 0) + 1
            visitors_by_category = [{'category__name': k, 'count': v} for k, v in cat_counter.items()]
            # Peak hours
            peak_hours = {h: 0 for h in range(24)}
            for v in visitors:
                h = v.check_in_time.hour
                peak_hours[h] = peak_hours.get(h, 0) + 1
            analytics = {
                'total_visitors': total_visitors,
                'active_visitors': active_visitors,
                'checked_out_visitors': checked_out_visitors,
                'avg_duration_hours': avg_duration_hours,
                'daily_visitors': daily_visitors,
                'visitors_by_category': visitors_by_category,
                'peak_hours': peak_hours,
            }
        except Exception:
            analytics = {
                'total_visitors': visitors.count(),
                'active_visitors': 0,
                'checked_out_visitors': 0,
                'avg_duration_hours': 0.0,
                'daily_visitors': [],
                'visitors_by_category': [],
                'peak_hours': {h: 0 for h in range(24)},
            }
        
        # Define styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            spaceAfter=30,
        )
        
        # Optional: Organization logo at top - improved logo loading
        if primary_site:
            try:
                from site_settings.models import SiteLogo
                import os
                logo_path = None
                
                # First try: Load from SiteLogo model
                try:
                    site_logo = SiteLogo.objects.filter(site=primary_site).first()
                    if site_logo:
                        if site_logo.logo_light and site_logo.logo_light.name:
                            logo_path = site_logo.logo_light.path
                        elif site_logo.logo_dark and site_logo.logo_dark.name:
                            logo_path = site_logo.logo_dark.path
                except Exception:
                    pass
                
                # Second try: SiteConfiguration logo field
                if not logo_path:
                    try:
                        from site_settings.models import SiteConfiguration
                        site_config = SiteConfiguration.objects.first()
                        if site_config and site_config.logo and site_config.logo.name:
                            logo_path = site_config.logo.path
                    except Exception:
                        pass
                
                # Verify file exists before using
                if logo_path and os.path.exists(logo_path):
                    logo_img = Image(logo_path, width=1.4*inch, height=1.4*inch)
                    elements.append(logo_img)
                    elements.append(Spacer(1, 8))
            except Exception:
                # If logo not available, continue silently
                pass

        # Title
        title = Paragraph(f'Visitor Report<br/>{date_from} to {date_to}', title_style)
        elements.append(title)
        elements.append(Spacer(1, 12))
        
        # Summary table
        summary_data = [
            ['Metric', 'Value'],
            ['Total Visitors', str(analytics['total_visitors'])],
            ['Active Visitors', str(analytics['active_visitors'])],
            ['Checked Out Visitors', str(analytics['checked_out_visitors'])],
            ['Average Duration (hours)', str(analytics['avg_duration_hours'])]
        ]
        
        summary_table = Table(summary_data)
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 14),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        elements.append(summary_table)
        elements.append(Spacer(1, 20))
        
        # Optional: Map image from OSM static maps (geocoded by postal code)
        if primary_site and getattr(primary_site, 'postal_code', None):
            try:
                import urllib.request, urllib.parse
                postal = str(primary_site.postal_code)
                q = urllib.parse.quote(f"{postal} Singapore")
                geo_url = f"https://nominatim.openstreetmap.org/search?q={q}&format=json&limit=1"
                req = urllib.request.Request(geo_url, headers={'User-Agent': 'monolith-vms/1.0'})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    geo = json.loads(resp.read().decode('utf-8'))
                if isinstance(geo, list) and geo:
                    lat = float(geo[0]['lat'])
                    lon = float(geo[0]['lon'])
                    static_url = (
                        f"https://staticmap.openstreetmap.de/staticmap.php?center={lat},{lon}"
                        f"&zoom=15&size=640x320&markers={lat},{lon},lightblue1"
                    )
                    req2 = urllib.request.Request(static_url, headers={'User-Agent': 'monolith-vms/1.0'})
                    with urllib.request.urlopen(req2, timeout=10) as img_resp:
                        img_bytes = img_resp.read()
                    img_buf = BytesIO(img_bytes)
                    map_img = Image(img_buf, width=6.3*inch, height=3.15*inch)
                    elements.append(Paragraph('Location Map', styles['Heading3']))
                    elements.append(map_img)
                    elements.append(Spacer(1, 16))
            except Exception:
                # If any error occurs, skip map gracefully
                elements.append(Paragraph('Map unavailable for this report.', styles['Italic']))
                elements.append(Spacer(1, 12))
        
        # Charts Section - build using ReportLab charts
        try:
            elements.append(Paragraph('Daily Visitors (Bar Chart)', styles['Heading3']))
            dv_width, dv_height = 460, 220
            dv = Drawing(dv_width, dv_height) if Drawing else None
            # Prepare data (limit labels to keep readable)
            dv_labels = [d['date'] for d in analytics['daily_visitors']]
            dv_values = [d['count'] for d in analytics['daily_visitors']]
            # Keep at most 20 points for readability
            if len(dv_labels) > 20:
                step = max(1, len(dv_labels)//20)
                dv_labels = dv_labels[::step]
                dv_values = dv_values[::step]
            dv_chart = VerticalBarChart() if VerticalBarChart else None
            dv_chart.x = 40
            dv_chart.y = 30
            dv_chart.height = dv_height - 60
            dv_chart.width = dv_width - 70
            dv_chart.data = [dv_values]
            dv_chart.categoryAxis.categoryNames = dv_labels
            dv_chart.categoryAxis.labels.angle = 45
            dv_chart.bars[0].fillColor = colors.Color(0.25, 0.5, 0.9)
            if dv and dv_chart:
                dv.add(dv_chart)
                elements.append(dv)
            elements.append(Spacer(1, 12))
            
            # Category distribution (Pie)
            cat_names = [(c.get('category__name') or 'Uncategorized') for c in analytics['visitors_by_category']]
            cat_values = [c['count'] for c in analytics['visitors_by_category']]
            if cat_values and sum(cat_values) > 0 and Pie:
                elements.append(Paragraph('Visitors by Category (Pie Chart)', styles['Heading3']))
                pie_d = Drawing(300, 220) if Drawing else None
                pie = Pie()
                pie.x = 65
                pie.y = 20
                pie.width = 170
                pie.height = 170
                pie.data = cat_values
                pie.labels = cat_names
                pie.sideLabels = True
                pie.slices.strokeWidth = 0.5
                if pie_d:
                    pie_d.add(pie)
                    elements.append(pie_d)
                elements.append(Spacer(1, 12))
            
            # Peak hours (Bar)
            elements.append(Paragraph('Peak Hours (Visitors per Hour)', styles['Heading3']))
            ph_width, ph_height = 460, 220
            ph = Drawing(ph_width, ph_height) if Drawing else None
            ph_labels = [f"{h:02d}:00" for h in range(24)]
            ph_values = [analytics['peak_hours'].get(h, 0) for h in range(24)]
            ph_chart = VerticalBarChart() if VerticalBarChart else None
            ph_chart.x = 40
            ph_chart.y = 30
            ph_chart.height = ph_height - 60
            ph_chart.width = ph_width - 70
            ph_chart.data = [ph_values]
            ph_chart.categoryAxis.categoryNames = ph_labels
            ph_chart.categoryAxis.labels.angle = 45
            ph_chart.bars[0].fillColor = colors.purple
            if ph and ph_chart:
                ph.add(ph_chart)
                elements.append(ph)
            elements.append(Spacer(1, 16))
        except Exception:
            elements.append(Paragraph('Charts unavailable for this report.', styles['Italic']))
            elements.append(Spacer(1, 12))

        # Visitor List Table (matches current filters)
        try:
            elements.append(Paragraph('Visitor List', styles['Heading3']))
            elements.append(Spacer(1, 6))

            # Define table headers (include requested fields)
            table_headers = [
                'Visitor', 'Company', 'Vehicle', 'Tower', 'Level', 'Unit',
                'Purpose', 'Category', 'Check-in', 'Status', 'Duration'
            ]

            # Build table rows from filtered visitors
            table_rows = []
            for v in visitors:
                # Status and duration
                is_checked_out = bool(v.check_out_time)
                status_text = 'Checked Out' if is_checked_out else 'Active'
                end_time = v.check_out_time or timezone.now()
                duration_td = end_time - v.check_in_time if v.check_in_time else timezone.timedelta(0)
                # Format duration as Hh Mm
                total_seconds = int(duration_td.total_seconds())
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                duration_text = f"{hours}h {minutes}m"

                # Safe strings
                company_text = v.company or '-'
                category_text = v.category.name if getattr(v, 'category', None) else '-'
                checkin_text = timezone.localtime(v.check_in_time).strftime('%Y-%m-%d %H:%M') if v.check_in_time else '-'
                vehicle_text = v.vehicle_number or '-'
                tower_text = getattr(v, 'tower', None) or '-'
                level_text = getattr(v, 'level', None) or '-'
                unit_text = getattr(v, 'unit', None) or '-'
                purpose_text = getattr(v, 'purpose', None) or '-'

                table_rows.append([
                    v.full_name,
                    company_text,
                    vehicle_text,
                    tower_text,
                    level_text,
                    unit_text,
                    purpose_text,
                    category_text,
                    checkin_text,
                    status_text,
                    duration_text,
                ])

            data = [table_headers] + table_rows

            # Create and style table
            visitor_table = Table(data, repeatRows=1)
            visitor_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4B5563')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                # Center alignment for compact columns
                ('ALIGN', (2, 1), (7, -1), 'CENTER'),
                ('ALIGN', (8, 1), (10, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ]))

            elements.append(visitor_table)
            elements.append(Spacer(1, 12))
        except Exception:
            # If table fails for any reason, continue with PDF
            elements.append(Paragraph('Visitor list unavailable.', styles['Italic']))
            elements.append(Spacer(1, 8))
        
        # Footer callback with site information and page number
        def _footer(canvas, _doc):
            try:
                canvas.saveState()
                canvas.setFont('Helvetica', 8)
                canvas.setFillColor(colors.grey)
                left_parts = []
                if primary_site and getattr(primary_site, 'name', None):
                    left_parts.append(primary_site.name)
                if primary_site and getattr(primary_site, 'address', None):
                    left_parts.append(str(primary_site.address))
                if primary_site and getattr(primary_site, 'postal_code', None):
                    left_parts.append(str(primary_site.postal_code))
                left_text = ' • '.join([p for p in left_parts if p])
                canvas.drawString(_doc.leftMargin, 0.5*inch, left_text[:180])
                canvas.drawRightString(_doc.pagesize[0]-_doc.rightMargin, 0.5*inch, f"Page {_doc.page}")
                canvas.restoreState()
            except Exception:
                pass
        # Build PDF
        doc.build(elements, onFirstPage=_footer, onLaterPages=_footer)
        pdf = buffer.getvalue()
        buffer.close()
        response.write(pdf)
        
        return response
    
    # Fallback to CSV if format not supported
    return export_visitor_data(visitors, 'csv', request)

@login_required
def pre_registration_reports(request):
    """Pre-registration reports with filtering and export capabilities"""
    user_profile = request.user.profile

    # Disallow Security Officer from this page
    if getattr(user_profile, 'is_security_officer', False):
        messages.error(request, "You don't have permission to access Pre-Registration Reports")
        return redirect('reports:dashboard')
    
    # Get filter parameters
    search = request.GET.get('search', '')
    status = request.GET.get('status', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    creator = request.GET.get('creator', '')
    export_format = request.GET.get('export', '')
    
    # Build query for pre-registrations
    pre_registrations = PreRegistration.objects.select_related(
        'visitor', 'registered_by', 'visitor__category'
    ).order_by('-created_at')

    # Restrict visibility for Staff to only their own records (admins/management/security see all)
    if getattr(user_profile, 'is_staff', False) and not (
        getattr(user_profile, 'is_management', False)
        or getattr(user_profile, 'is_admin', False)
        or getattr(user_profile, 'is_security_officer', False)
        or getattr(request.user, 'is_superuser', False)
    ):
        pre_registrations = pre_registrations.filter(registered_by=request.user)
    
    # Apply search filter
    if search:
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
    
    # Apply creator filter
    if creator:
        pre_registrations = pre_registrations.filter(registered_by__id=creator)
    
    # Apply date filter
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            pre_registrations = pre_registrations.filter(created_at__date__gte=date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            pre_registrations = pre_registrations.filter(created_at__date__lte=date_to_obj)
        except ValueError:
            pass
    
    # Handle export
    if export_format in ['csv', 'excel', 'pdf']:
        return export_pre_registration_data(pre_registrations, date_from, date_to, export_format)
    
    # Pagination for web view
    from django.core.paginator import Paginator
    paginator = Paginator(pre_registrations, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get all creators for filter dropdown (limited to visible queryset)
    from django.contrib.auth.models import User
    visible_creator_ids = pre_registrations.values_list('registered_by_id', flat=True).distinct()
    creators = User.objects.filter(id__in=list(visible_creator_ids)).order_by('first_name', 'last_name', 'username')
    
    # Calculate statistics
    total_count = pre_registrations.count()
    used_count = pre_registrations.filter(is_used=True).count()
    unused_count = pre_registrations.filter(is_used=False).count()
    expired_count = pre_registrations.filter(expires_at__lt=timezone.now(), is_used=False).count()
    
    context = {
        'page_obj': page_obj,
        'pre_registrations': page_obj.object_list,
        'total_count': total_count,
        'used_count': used_count,
        'unused_count': unused_count,
        'expired_count': expired_count,
        'creators': creators,
        'filters': {
            'search': search,
            'status': status,
            'date_from': date_from,
            'date_to': date_to,
            'creator': creator,
        }
    }
    
    return render(request, 'reports/pre_registration_reports.html', context)

def export_pre_registration_data(pre_registrations, date_from, date_to, format_type):
    """Export pre-registration data in various formats"""
    
    if format_type == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="pre_registration_report_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'Visitor Name', 'Contact Number', 'Company', 'Category', 
            'Invited By', 'Created Date', 'Expires Date', 'Expected Arrival', 'Status', 
            'Used Date', 'Purpose', 'Unique Link'
        ])
        
        for pre_reg in pre_registrations:
            status = 'Used' if pre_reg.is_used else ('Expired' if pre_reg.is_expired else 'Pending')
            creator_name = f"{pre_reg.registered_by.first_name} {pre_reg.registered_by.last_name}".strip() or pre_reg.registered_by.username
            expected_arrival = ''
            if pre_reg.expected_arrival_date and pre_reg.expected_arrival_time:
                expected_arrival = f"{pre_reg.expected_arrival_date.strftime('%Y-%m-%d')} {pre_reg.expected_arrival_time.strftime('%H:%M')}"
            elif pre_reg.expected_arrival_date:
                expected_arrival = pre_reg.expected_arrival_date.strftime('%Y-%m-%d')
            
            writer.writerow([
                pre_reg.visitor.full_name,
                pre_reg.visitor.contact_number or '',
                pre_reg.visitor.company or '',
                pre_reg.visitor.category.name if pre_reg.visitor.category else '',
                creator_name,
                timezone.localtime(pre_reg.created_at).strftime('%Y-%m-%d %H:%M:%S'),
                timezone.localtime(pre_reg.expires_at).strftime('%Y-%m-%d %H:%M:%S'),
                expected_arrival,
                status,
                timezone.localtime(pre_reg.used_at).strftime('%Y-%m-%d %H:%M:%S') if pre_reg.used_at else '',
                pre_reg.visitor.purpose or '',
                f"https://example.com/visitors/pre-register/{pre_reg.unique_link}/"
            ])
        
        return response
    
    elif format_type == 'excel' and openpyxl:
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="pre_registration_report_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'
        
        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.title = 'Pre-Registration Report'
        
        # Headers
        headers = [
            'Visitor Name', 'Contact Number', 'Company', 'Category', 
            'Created By', 'Created Date', 'Expires Date', 'Status', 
            'Used Date', 'Purpose', 'Unique Link'
        ]
        
        for col, header in enumerate(headers, 1):
            cell = worksheet.cell(row=1, column=col, value=header)
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal='center')
        
        # Data
        for row, pre_reg in enumerate(pre_registrations, 2):
            status = 'Used' if pre_reg.is_used else ('Expired' if pre_reg.is_expired else 'Pending')
            creator_name = f"{pre_reg.registered_by.first_name} {pre_reg.registered_by.last_name}".strip() or pre_reg.registered_by.username
            
            data = [
                pre_reg.visitor.full_name,
                pre_reg.visitor.contact_number or '',
                pre_reg.visitor.company or '',
                pre_reg.visitor.category.name if pre_reg.visitor.category else '',
                creator_name,
                pre_reg.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                pre_reg.expires_at.strftime('%Y-%m-%d %H:%M:%S'),
                status,
                pre_reg.used_at.strftime('%Y-%m-%d %H:%M:%S') if pre_reg.used_at else '',
                pre_reg.visitor.purpose or '',
                f"https://example.com/visitors/pre-register/{pre_reg.unique_link}/"
            ]
            
            for col, value in enumerate(data, 1):
                worksheet.cell(row=row, column=col, value=value)
        
        # Auto-adjust column widths
        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            worksheet.column_dimensions[column_letter].width = adjusted_width
        
        workbook.save(response)
        return response
    
    elif format_type == 'pdf' and SimpleDocTemplate:
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="pre_registration_report_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
        
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        elements = []
        
        # Styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            spaceAfter=30,
            alignment=1  # Center alignment
        )
        
        # Title
        title = Paragraph("Pre-Registration Report", title_style)
        elements.append(title)
        elements.append(Spacer(1, 12))
        
        # Date range
        if date_from or date_to:
            date_range = f"Period: {date_from or 'Start'} to {date_to or 'End'}"
            date_para = Paragraph(date_range, styles['Normal'])
            elements.append(date_para)
            elements.append(Spacer(1, 12))
        
        # Table data
        data = [[
            'Visitor Name', 'Company', 'Category', 'Invited By', 
            'Created Date', 'Expected Arrival', 'Status'
        ]]
        
        for pre_reg in pre_registrations:
            status = 'Used' if pre_reg.is_used else ('Expired' if pre_reg.is_expired else 'Pending')
            creator_name = f"{pre_reg.registered_by.first_name} {pre_reg.registered_by.last_name}".strip() or pre_reg.registered_by.username
            expected_arrival = ''
            if pre_reg.expected_arrival_date and pre_reg.expected_arrival_time:
                expected_arrival = f"{pre_reg.expected_arrival_date.strftime('%Y-%m-%d')} {pre_reg.expected_arrival_time.strftime('%H:%M')}"
            elif pre_reg.expected_arrival_date:
                expected_arrival = pre_reg.expected_arrival_date.strftime('%Y-%m-%d')
            
            data = [
                pre_reg.visitor.full_name,
                pre_reg.visitor.contact_number or '',
                pre_reg.visitor.company or '',
                pre_reg.visitor.category.name if pre_reg.visitor.category else '',
                creator_name,
                timezone.localtime(pre_reg.created_at).strftime('%Y-%m-%d %H:%M:%S'),
                timezone.localtime(pre_reg.expires_at).strftime('%Y-%m-%d %H:%M:%S'),
                expected_arrival,
                status,
                timezone.localtime(pre_reg.used_at).strftime('%Y-%m-%d %H:%M:%S') if pre_reg.used_at else '',
                pre_reg.visitor.purpose or '',
                f"https://example.com/visitors/pre-register/{pre_reg.unique_link}/"
            ]
            
            data.append([
                pre_reg.visitor.full_name,
                pre_reg.visitor.company or '-',
                pre_reg.visitor.category.name if pre_reg.visitor.category else '-',
                creator_name,
                timezone.localtime(pre_reg.created_at).strftime('%Y-%m-%d'),
                expected_arrival or '-',
                status
            ])
        
        # Create table
        table = Table(data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        elements.append(table)
        
        # Build PDF
        doc.build(elements)
        pdf = buffer.getvalue()
        buffer.close()
        response.write(pdf)
        
        return response
    
    # Fallback to CSV if format not supported
    return export_pre_registration_data(pre_registrations, date_from, date_to, 'csv')


@login_required
@can_view_reports
def analytics_report(request):
    """Render analytics dashboard with computed metrics and charts."""
    primary_site = Site.objects.filter(is_active=True).first()

    # Get analytics type from request (visitor or vehicle)
    analytics_type = request.GET.get('analytics_type', 'visitor')
    
    # Filters taken from request
    date_from_str = request.GET.get('date_from') or ''
    date_to_str = request.GET.get('date_to') or ''

    # Build filtered queryset
    # Reuse the same filter logic as visitor report
    visitors = Visitor.objects.all()
    category_id = request.GET.get('category')
    status = request.GET.get('status')
    search = request.GET.get('search')

    if category_id:
        visitors = visitors.filter(category_id=category_id)

    # Date range filters
    date_from = None
    date_to = None
    try:
        if date_from_str:
            date_from = datetime.strptime(date_from_str, '%Y-%m-%d').date()
            visitors = visitors.filter(check_in_time__date__gte=date_from)
    except ValueError:
        date_from = None
    try:
        if date_to_str:
            date_to = datetime.strptime(date_to_str, '%Y-%m-%d').date()
            visitors = visitors.filter(check_in_time__date__lte=date_to)
    except ValueError:
        date_to = None

    if status == 'active':
        visitors = visitors.filter(check_out_time__isnull=True)
    elif status == 'checked_out':
        visitors = visitors.filter(check_out_time__isnull=False)

    if search:
        visitors = visitors.filter(
            Q(full_name__icontains=search) |
            Q(company__icontains=search) |
            Q(contact_number__icontains=search) |
            Q(pass_number__icontains=search) |
            Q(purpose__icontains=search) |
            Q(ic_last_digits__icontains=search) |
            Q(vehicle_number__icontains=search) |
            Q(category__name__icontains=search)
        )

    # Support analytics exports via query param to match template buttons
    export_format = (request.GET.get('export') or '').lower()
    if export_format in {'csv', 'excel', 'pdf'}:
        return export_visitor_data(visitors, export_format, request)

    visitors = visitors.select_related('category')

    # Compute analytics
    try:
        total_visitors = visitors.count()
        active_visitors = visitors.filter(check_out_time__isnull=True).count()
        checked_out_visitors = total_visitors - active_visitors
        total_hours = 0.0
        for v in visitors:
            end_time = v.check_out_time or timezone.now()
            total_hours += max(0.0, (end_time - v.check_in_time).total_seconds() / 3600.0)
        avg_duration_hours = round((total_hours / total_visitors), 1) if total_visitors else 0.0

        dv_counter = {}
        for v in visitors:
            d = v.check_in_time.date().isoformat()
            dv_counter[d] = dv_counter.get(d, 0) + 1
        daily_visitors = [{'date': d, 'count': c} for d, c in sorted(dv_counter.items())]

        cat_counter = {}
        for v in visitors:
            name = v.category.name if v.category else 'Uncategorized'
            cat_counter[name] = cat_counter.get(name, 0) + 1
        visitors_by_category = [{'category__name': k, 'count': v} for k, v in cat_counter.items()]

        peak_hours = {h: 0 for h in range(24)}
        for v in visitors:
            h = v.check_in_time.hour
            peak_hours[h] = peak_hours.get(h, 0) + 1

        # Vehicle analytics
        vehicle_whitelist = ALPRWhitelist.objects.all()
        if date_from:
            vehicle_whitelist = vehicle_whitelist.filter(whitelisted_at__date__gte=date_from)
        if date_to:
            vehicle_whitelist = vehicle_whitelist.filter(whitelisted_at__date__lte=date_to)
        
        total_vehicle_entries = vehicle_whitelist.count()
        active_vehicle_entries = vehicle_whitelist.filter(is_active=True, expires_at__gt=timezone.now()).count()
        synced_vehicle_entries = vehicle_whitelist.filter(synced_to_camera=True).count()
        sync_error_entries = vehicle_whitelist.filter(sync_error__isnull=False).exclude(sync_error='').count()
        
        # Vehicle registration trend (last 7 days)
        vehicle_daily_trend = []
        for i in range(7):
            day = timezone.now().date() - timedelta(days=i)
            day_count = vehicle_whitelist.filter(whitelisted_at__date=day).count()
            vehicle_daily_trend.append({
                'date': day.strftime('%Y-%m-%d'),
                'count': day_count
            })
        vehicle_daily_trend.reverse()

        analytics = {
            'total_visitors': total_visitors,
            'active_visitors': active_visitors,
            'checked_out_visitors': checked_out_visitors,
            'avg_duration_hours': avg_duration_hours,
            'daily_visitors': daily_visitors,
            'visitors_by_category': visitors_by_category,
            'peak_hours': peak_hours,
        }
        
        # Vehicle analytics data
        vehicle_analytics = {
            'total_vehicles': total_vehicle_entries,
            'active_vehicles': active_vehicle_entries,
            'synced_vehicles': synced_vehicle_entries,
            'sync_error_vehicles': sync_error_entries,
            'vehicle_trend': vehicle_daily_trend,
            'sync_success_rate': round((synced_vehicle_entries / total_vehicle_entries * 100), 1) if total_vehicle_entries > 0 else 0,
        }
    except Exception:
        analytics = {
            'total_visitors': visitors.count(),
            'active_visitors': 0,
            'checked_out_visitors': 0,
            'avg_duration_hours': 0.0,
            'daily_visitors': [],
            'visitors_by_category': [],
            'peak_hours': {h: 0 for h in range(24)},
        }
        
        vehicle_analytics = {
            'total_vehicles': 0,
            'active_vehicles': 0,
            'synced_vehicles': 0,
            'sync_error_vehicles': 0,
            'vehicle_trend': [],
            'sync_success_rate': 0,
        }

    context = {
        'primary_site': primary_site,
        'date_from': date_from,
        'date_to': date_to,
        'analytics_type': analytics_type,
        'analytics': analytics,
        'vehicle_analytics': vehicle_analytics,
    }
    return render(request, 'reports/analytics.html', context)


@login_required
def export_visitors_csv(request):
    """Export visitors with current filters to CSV."""
    visitors = _filtered_visitors_queryset(request)
    return export_visitor_data(visitors, 'csv', request)


@login_required
def export_visitors_excel(request):
    """Export visitors with current filters to Excel."""
    visitors = _filtered_visitors_queryset(request)
    return export_visitor_data(visitors, 'excel', request)


@login_required
def export_visitors_pdf(request):
    """Export visitors with current filters to PDF, including analytics and charts."""
    visitors = _filtered_visitors_queryset(request)
    return export_visitor_data(visitors, 'pdf', request)


def _filtered_visitors_queryset(request):
    """Build a visitors queryset based on request filters."""
    visitors = Visitor.objects.all()

    category_id = request.GET.get('category')
    if category_id:
        visitors = visitors.filter(category_id=category_id)

    # Date range
    date_from_str = request.GET.get('date_from') or ''
    date_to_str = request.GET.get('date_to') or ''
    try:
        if date_from_str:
            date_from = datetime.strptime(date_from_str, '%Y-%m-%d').date()
            visitors = visitors.filter(check_in_time__date__gte=date_from)
    except ValueError:
        pass
    try:
        if date_to_str:
            date_to = datetime.strptime(date_to_str, '%Y-%m-%d').date()
            visitors = visitors.filter(check_in_time__date__lte=date_to)
    except ValueError:
        pass

    status = request.GET.get('status')
    if status == 'active':
        visitors = visitors.filter(check_out_time__isnull=True)
    elif status == 'checked_out':
        visitors = visitors.filter(check_out_time__isnull=False)

    search = request.GET.get('search')
    if search:
        visitors = visitors.filter(
            Q(full_name__icontains=search) |
            Q(company__icontains=search) |
            Q(contact_number__icontains=search) |
            Q(pass_number__icontains=search) |
            Q(purpose__icontains=search) |
            Q(ic_last_digits__icontains=search) |
            Q(vehicle_number__icontains=search) |
            Q(category__name__icontains=search)
        )

    sort_by = request.GET.get('sort', '-check_in_time')
    valid_sort_fields = [
        'check_in_time', '-check_in_time',
        'full_name', '-full_name',
        'company', '-company',
        'category__name', '-category__name',
        'check_out_time', '-check_out_time'
    ]
    if sort_by in valid_sort_fields:
        visitors = visitors.order_by(sort_by)
    else:
        visitors = visitors.order_by('-check_in_time')

    return visitors.select_related('category')


@login_required
def visitor_detail_api(request, visitor_id):
    """Return minimal visitor details as JSON."""
    visitor = get_object_or_404(Visitor, id=visitor_id)
    data = {
        'id': visitor.id,
        'full_name': visitor.full_name,
        'company': visitor.company or '',
        'contact_number': visitor.contact_number or '',
        'category': visitor.category.name if visitor.category else None,
        'status': 'Checked Out' if visitor.check_out_time else 'Active',
    }
    return JsonResponse({'success': True, 'visitor': data})


@login_required
def visitor_detail_full_api(request, visitor_id):
    """Return extended visitor details as JSON."""
    visitor = get_object_or_404(Visitor, id=visitor_id)
    data = {
        'id': visitor.id,
        'full_name': visitor.full_name,
        'company': visitor.company or '',
        'contact_number': visitor.contact_number or '',
        'category': visitor.category.name if visitor.category else None,
        'category_id': visitor.category_id,
        'check_in_time': timezone.localtime(visitor.check_in_time).strftime('%Y-%m-%d %H:%M') if visitor.check_in_time else None,
        'check_out_time': timezone.localtime(visitor.check_out_time).strftime('%Y-%m-%d %H:%M') if visitor.check_out_time else None,
        'pass_number': visitor.pass_number or '',
        'vehicle_number': visitor.vehicle_number or '',
        'tower': visitor.tower or '',
        'level': visitor.level or '',
        'unit': visitor.unit or '',
        'purpose': visitor.purpose or '',
        'ic_last_digits': visitor.ic_last_digits or '',
        'status': 'Checked Out' if visitor.check_out_time else 'Active',
        'is_pre_registered': visitor.is_pre_registered,
    }
    # Include inviter information for pre-registered visitors
    invited_by = ''
    expected_arrival = ''
    verified_by = ''
    verified_at = ''
    try:
        if visitor.is_pre_registered and hasattr(visitor, 'pre_registration'):
            prereg = visitor.pre_registration
            inviter = prereg.registered_by
            if inviter:
                invited_by = (inviter.get_full_name() or inviter.username)
            # Expected arrival
            if prereg.expected_arrival_date and prereg.expected_arrival_time:
                expected_arrival = f"{prereg.expected_arrival_date.strftime('%Y-%m-%d')} {prereg.expected_arrival_time.strftime('%H:%M')}"
            elif prereg.expected_arrival_date:
                expected_arrival = prereg.expected_arrival_date.strftime('%Y-%m-%d')
            # Verified info
            if prereg.verified_by:
                verified_by = (prereg.verified_by.get_full_name() or prereg.verified_by.username)
            if prereg.verified_at:
                verified_at = timezone.localtime(prereg.verified_at).strftime('%Y-%m-%d %H:%M')
    except Exception:
        invited_by = invited_by or ''
        expected_arrival = expected_arrival or ''
        verified_by = verified_by or ''
        verified_at = verified_at or ''
    data['invited_by'] = invited_by
    data['expected_arrival'] = expected_arrival
    data['verified_by'] = verified_by
    data['verified_at'] = verified_at
    return JsonResponse({'success': True, 'visitor': data})


@login_required
@require_POST
def visitor_checkout_api(request, visitor_id):
    """Mark a visitor as checked out."""
    visitor = get_object_or_404(Visitor, id=visitor_id)
    if visitor.check_out_time:
        return JsonResponse({'success': True, 'message': 'Already checked out.'})
    visitor.check_out_time = timezone.now()
    visitor.save(update_fields=['check_out_time'])
    return JsonResponse({'success': True})


@login_required
@require_POST
def verify_password_api(request):
    """Verify the current user's password. Expects 'password' in POST."""
    password = request.POST.get('password', '')
    ok = request.user.check_password(password) if password else False
    return JsonResponse({'success': ok})


@login_required
@require_POST
def visitor_edit_api(request, visitor_id):
    """Edit visitor data. Only allowed for visitors who are still checked in."""
    visitor = get_object_or_404(Visitor, id=visitor_id)
    
    if visitor.check_out_time:
        return JsonResponse({'success': False, 'error': 'Cannot edit checked-out visitors.'}, status=400)
    
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data.'}, status=400)
    
    editable_fields = [
        'full_name', 'contact_number', 'ic_last_digits', 'company',
        'vehicle_number', 'tower', 'level', 'unit', 'purpose'
    ]
    
    updated_fields = []
    for field in editable_fields:
        if field in data:
            old_value = getattr(visitor, field, None)
            new_value = data[field].strip() if data[field] else ''
            if old_value != new_value:
                setattr(visitor, field, new_value if new_value else None)
                updated_fields.append(field)
    
    if 'category_id' in data:
        try:
            category_id = int(data['category_id']) if data['category_id'] else None
            if category_id:
                category = VisitorCategory.objects.get(id=category_id, is_active=True)
                if visitor.category_id != category_id:
                    visitor.category = category
                    updated_fields.append('category')
            else:
                if visitor.category_id:
                    visitor.category = None
                    updated_fields.append('category')
        except (ValueError, VisitorCategory.DoesNotExist):
            pass
    
    if updated_fields:
        visitor.save()
        ActivityLog.objects.create(
            user=request.user,
            action='edit',
            description=f"Edited visitor {visitor.full_name} (ID: {visitor.id}). Fields updated: {', '.join(updated_fields)}",
            ip_address=request.META.get('REMOTE_ADDR', '')
        )
    
    return JsonResponse({
        'success': True,
        'message': f'Visitor updated successfully. Fields updated: {", ".join(updated_fields)}' if updated_fields else 'No changes made.',
        'updated_fields': updated_fields
    })


@login_required
def vehicle_report(request):
    """Vehicle reports with ALPR whitelist analytics"""
    user_profile = request.user.profile
    
    # Get filter parameters
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    sync_filter = request.GET.get('sync', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    site_filter = request.GET.get('site', '')
    
    # Base queryset
    whitelist_entries = ALPRWhitelist.objects.select_related('visitor', 'created_by').all()
    
    # Apply filters
    if search_query:
        whitelist_entries = whitelist_entries.filter(
            Q(plate_number__icontains=search_query) |
            Q(visitor__first_name__icontains=search_query) |
            Q(visitor__last_name__icontains=search_query) |
            Q(visitor__company__icontains=search_query)
        )
    
    if status_filter:
        if status_filter == 'active':
            whitelist_entries = whitelist_entries.filter(is_active=True, expires_at__gt=timezone.now())
        elif status_filter == 'expired':
            whitelist_entries = whitelist_entries.filter(expires_at__lte=timezone.now())
        elif status_filter == 'inactive':
            whitelist_entries = whitelist_entries.filter(is_active=False)
    
    if sync_filter:
        if sync_filter == 'synced':
            whitelist_entries = whitelist_entries.filter(synced_to_camera=True)
        elif sync_filter == 'unsynced':
            whitelist_entries = whitelist_entries.filter(synced_to_camera=False)
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            whitelist_entries = whitelist_entries.filter(whitelisted_at__date__gte=date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            whitelist_entries = whitelist_entries.filter(whitelisted_at__date__lte=date_to_obj)
        except ValueError:
            pass
    
    if site_filter and user_profile.role == 'admin':
        whitelist_entries = whitelist_entries.filter(visitor__site_id=site_filter)
    elif user_profile.role != 'admin':
        # Non-admin users see only their site's data
        whitelist_entries = whitelist_entries.filter(visitor__site=user_profile.site)
    
    # Calculate statistics
    total_entries = whitelist_entries.count()
    active_entries = whitelist_entries.filter(is_active=True, expires_at__gt=timezone.now()).count()
    expired_entries = whitelist_entries.filter(expires_at__lte=timezone.now()).count()
    synced_entries = whitelist_entries.filter(synced_to_camera=True).count()
    unsynced_entries = whitelist_entries.filter(synced_to_camera=False).count()
    
    # Recent activity (last 30 days)
    thirty_days_ago = timezone.now() - timedelta(days=30)
    recent_entries = whitelist_entries.filter(whitelisted_at__gte=thirty_days_ago).count()
    
    # Sync error statistics
    sync_errors = whitelist_entries.filter(sync_error__isnull=False).exclude(sync_error='').count()
    
    # Top companies by vehicle count
    top_companies = (whitelist_entries
                    .values('visitor__company')
                    .annotate(vehicle_count=Count('id'))
                    .order_by('-vehicle_count')[:5])
    
    # Monthly trend data (last 12 months)
    monthly_data = []
    for i in range(12):
        month_start = timezone.now().replace(day=1) - timedelta(days=30*i)
        month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        month_count = whitelist_entries.filter(
            whitelisted_at__date__gte=month_start.date(),
            whitelisted_at__date__lte=month_end.date()
        ).count()
        monthly_data.append({
            'month': month_start.strftime('%b %Y'),
            'count': month_count
        })
    monthly_data.reverse()
    
    # Pagination
    paginator = Paginator(whitelist_entries.order_by('-whitelisted_at'), 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get sites for filter (admin only)
    sites = Site.objects.filter(is_active=True) if user_profile.role == 'admin' else []
    
    context = {
        'whitelist_entries': page_obj,
        'search_query': search_query,
        'status_filter': status_filter,
        'sync_filter': sync_filter,
        'date_from': date_from,
        'date_to': date_to,
        'site_filter': site_filter,
        'sites': sites,
        'user_role': user_profile.role,
        'statistics': {
            'total_entries': total_entries,
            'active_entries': active_entries,
            'expired_entries': expired_entries,
            'synced_entries': synced_entries,
            'unsynced_entries': unsynced_entries,
            'recent_entries': recent_entries,
            'sync_errors': sync_errors,
        },
        'top_companies': top_companies,
        'monthly_data': json.dumps(monthly_data),
    }
    
    return render(request, 'reports/vehicle_report.html', context)


@login_required
@can_view_reports
def resident_history_report(request):
    """Generate resident vehicle history reports with filters and export options"""
    user_profile = request.user.profile
    export_format = (request.GET.get('export') or '').strip().lower()
    
    # Get filter parameters
    search = request.GET.get('search', '').strip()
    direction = request.GET.get('direction', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    page = request.GET.get('page', 1)
    
    # Build query
    logs = ResidentVehicleLog.objects.select_related('resident', 'vehicle').all()
    
    # Apply filters
    if search:
        logs = logs.filter(
            Q(plate_number__icontains=search) |
            Q(resident__full_name__icontains=search) |
            Q(resident__tower__icontains=search) |
            Q(resident__unit__icontains=search) |
            Q(resident__phone_number__icontains=search)
        )
    
    if direction in ['in', 'out']:
        logs = logs.filter(direction=direction)
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            logs = logs.filter(detected_at__date__gte=date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            logs = logs.filter(detected_at__date__lte=date_to_obj)
        except ValueError:
            pass
    
    logs = logs.order_by('-detected_at')
    
    # Statistics
    today = timezone.now().date()
    total_logs = ResidentVehicleLog.objects.count()
    today_logs = ResidentVehicleLog.objects.filter(detected_at__date=today).count()
    today_in = ResidentVehicleLog.objects.filter(detected_at__date=today, direction='in').count()
    today_out = ResidentVehicleLog.objects.filter(detected_at__date=today, direction='out').count()
    unique_residents = ResidentVehicleLog.objects.values('resident').distinct().count()
    unique_plates = ResidentVehicleLog.objects.values('plate_number').distinct().count()
    
    # Handle export
    if export_format in {'csv', 'excel', 'pdf'}:
        return export_resident_history(logs, export_format, request)
    
    # Pagination
    paginator = Paginator(logs, 50)
    try:
        page_obj = paginator.page(page)
    except:
        page_obj = paginator.page(1)
    
    context = {
        'logs': page_obj.object_list,
        'page_obj': page_obj,
        'filters': {
            'search': search,
            'direction': direction,
            'date_from': date_from,
            'date_to': date_to,
        },
        'statistics': {
            'total_logs': total_logs,
            'today_logs': today_logs,
            'today_in': today_in,
            'today_out': today_out,
            'unique_residents': unique_residents,
            'unique_plates': unique_plates,
        },
        'total_count': logs.count(),
    }
    
    return render(request, 'reports/resident_history_report.html', context)


def export_resident_history(queryset, export_format, request):
    """Export resident vehicle history to CSV, Excel, or PDF"""
    logs = list(queryset[:5000])  # Limit exports to 5000 records
    
    if export_format == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="resident_history_report.csv"'
        writer = csv.writer(response)
        writer.writerow(['Plate Number', 'Resident Name', 'Tower', 'Level', 'Unit', 'Phone', 'Direction', 'Detected At'])
        for log in logs:
            writer.writerow([
                log.plate_number,
                log.resident.full_name if log.resident else '-',
                log.resident.tower if log.resident else '-',
                log.resident.level if log.resident else '-',
                log.resident.unit if log.resident else '-',
                log.resident.phone_number if log.resident else '-',
                log.direction.upper(),
                log.detected_at.strftime('%Y-%m-%d %H:%M:%S') if log.detected_at else '-',
            ])
        return response
    
    elif export_format == 'excel' and openpyxl:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Resident History"
        
        headers = ['Plate Number', 'Resident Name', 'Tower', 'Level', 'Unit', 'Phone', 'Direction', 'Detected At']
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.font = Font(bold=True)
        
        for row_num, log in enumerate(logs, 2):
            ws.cell(row=row_num, column=1, value=log.plate_number)
            ws.cell(row=row_num, column=2, value=log.resident.full_name if log.resident else '-')
            ws.cell(row=row_num, column=3, value=log.resident.tower if log.resident else '-')
            ws.cell(row=row_num, column=4, value=log.resident.level if log.resident else '-')
            ws.cell(row=row_num, column=5, value=log.resident.unit if log.resident else '-')
            ws.cell(row=row_num, column=6, value=log.resident.phone_number if log.resident else '-')
            ws.cell(row=row_num, column=7, value=log.direction.upper())
            ws.cell(row=row_num, column=8, value=log.detected_at.strftime('%Y-%m-%d %H:%M:%S') if log.detected_at else '-')
        
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename="resident_history_report.xlsx"'
        wb.save(response)
        return response
    
    elif export_format == 'pdf' and SimpleDocTemplate:
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        elements = []
        
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=18, alignment=1)
        elements.append(Paragraph("Resident Vehicle History Report", title_style))
        elements.append(Spacer(1, 20))
        
        # Add report info
        info_style = styles['Normal']
        elements.append(Paragraph(f"Generated: {timezone.now().strftime('%Y-%m-%d %H:%M')}", info_style))
        elements.append(Paragraph(f"Total Records: {len(logs)}", info_style))
        elements.append(Spacer(1, 20))
        
        # Table data
        data = [['Plate', 'Resident', 'Unit', 'Direction', 'Detected At']]
        for log in logs[:500]:  # Limit PDF to 500 rows for performance
            data.append([
                log.plate_number,
                log.resident.full_name[:20] if log.resident else '-',
                f"{log.resident.tower or ''}-{log.resident.level or ''}-{log.resident.unit or ''}" if log.resident else '-',
                log.direction.upper(),
                log.detected_at.strftime('%m/%d %H:%M') if log.detected_at else '-',
            ])
        
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        elements.append(table)
        
        doc.build(elements)
        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="resident_history_report.pdf"'
        return response
    
    # Fallback to CSV if format not supported
    return export_resident_history(queryset, 'csv', request)


@login_required
def activity_log_report(request):
    """
    Activity Log Report for super admin.
    Shows all user activities with search and filter capabilities.
    """
    user_profile = request.user.profile
    
    # Only allow admin role to view this report
    if user_profile.role != 'admin':
        messages.error(request, "You don't have permission to access this report.")
        return render(request, 'reports/dashboard.html')
    
    export_format = (request.GET.get('export') or '').strip().lower()
    
    # Get filter parameters
    search = request.GET.get('search', '').strip()
    action_filter = request.GET.get('action', '')
    module_filter = request.GET.get('module', '')
    user_filter = request.GET.get('user_id', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    page = request.GET.get('page', 1)
    
    # Build query
    logs = ActivityLog.objects.select_related('user').all()
    
    # Apply filters
    if search:
        logs = logs.filter(
            Q(description__icontains=search) |
            Q(user__username__icontains=search) |
            Q(user__first_name__icontains=search) |
            Q(user__last_name__icontains=search) |
            Q(target_type__icontains=search) |
            Q(ip_address__icontains=search)
        )
    
    if action_filter:
        logs = logs.filter(action=action_filter)
    
    if module_filter:
        logs = logs.filter(module=module_filter)
    
    if user_filter:
        logs = logs.filter(user_id=user_filter)
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            logs = logs.filter(created_at__date__gte=date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            logs = logs.filter(created_at__date__lte=date_to_obj)
        except ValueError:
            pass
    
    # Calculate statistics on UNFILTERED queryset for global totals
    today = timezone.now().date()
    all_logs = ActivityLog.objects.all()
    total_logs = all_logs.count()
    today_logs = all_logs.filter(created_at__date=today).count()
    unique_users = all_logs.values('user').distinct().count()
    
    # Action breakdown for today (global)
    today_logins = all_logs.filter(created_at__date=today, action='login').count()
    today_creates = all_logs.filter(created_at__date=today, action='create').count()
    today_updates = all_logs.filter(created_at__date=today, action='update').count()
    
    statistics = {
        'total_logs': total_logs,
        'today_logs': today_logs,
        'unique_users': unique_users,
        'today_logins': today_logins,
        'today_creates': today_creates,
        'today_updates': today_updates,
    }
    
    # Count filtered results
    filtered_count = logs.count()
    
    # Handle export
    if export_format in ['csv', 'excel', 'pdf']:
        return export_activity_log(logs, export_format, request)
    
    # Get users for filter dropdown
    users = User.objects.filter(is_active=True).order_by('username')
    
    # Pagination
    paginator = Paginator(logs, 50)
    try:
        logs_page = paginator.page(page)
    except:
        logs_page = paginator.page(1)
    
    context = {
        'logs': logs_page,
        'statistics': statistics,
        'total_count': filtered_count,
        'filters': {
            'search': search,
            'action': action_filter,
            'module': module_filter,
            'user_id': user_filter,
            'date_from': date_from,
            'date_to': date_to,
        },
        'users': users,
        'action_choices': ActivityLog.ACTION_CHOICES,
        'module_choices': ActivityLog.MODULE_CHOICES,
        'user_role': user_profile.role,
    }
    
    return render(request, 'reports/activity_log_report.html', context)


def export_activity_log(queryset, export_format, request):
    """Export activity logs to CSV, Excel, or PDF"""
    logs = list(queryset[:5000])
    
    if export_format == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="activity_log_report.csv"'
        writer = csv.writer(response)
        writer.writerow(['Date/Time', 'User', 'Action', 'Module', 'Description', 'IP Address'])
        for log in logs:
            writer.writerow([
                log.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                log.user.username if log.user else 'System',
                log.get_action_display(),
                log.get_module_display(),
                log.description[:100],
                log.ip_address or '-',
            ])
        return response
    
    elif export_format == 'excel' and openpyxl:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Activity Log"
        
        headers = ['Date/Time', 'User', 'Action', 'Module', 'Description', 'IP Address']
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.font = Font(bold=True)
        
        for row_num, log in enumerate(logs, 2):
            ws.cell(row=row_num, column=1, value=log.created_at.strftime('%Y-%m-%d %H:%M:%S'))
            ws.cell(row=row_num, column=2, value=log.user.username if log.user else 'System')
            ws.cell(row=row_num, column=3, value=log.get_action_display())
            ws.cell(row=row_num, column=4, value=log.get_module_display())
            ws.cell(row=row_num, column=5, value=log.description[:100])
            ws.cell(row=row_num, column=6, value=log.ip_address or '-')
        
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename="activity_log_report.xlsx"'
        wb.save(response)
        return response
    
    elif export_format == 'pdf' and SimpleDocTemplate:
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        elements = []
        
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=18, alignment=1)
        elements.append(Paragraph("Activity Log Report", title_style))
        elements.append(Spacer(1, 20))
        
        info_style = styles['Normal']
        elements.append(Paragraph(f"Generated: {timezone.now().strftime('%Y-%m-%d %H:%M')}", info_style))
        elements.append(Paragraph(f"Total Records: {len(logs)}", info_style))
        elements.append(Spacer(1, 20))
        
        data = [['Date/Time', 'User', 'Action', 'Module', 'Description']]
        for log in logs[:500]:
            data.append([
                log.created_at.strftime('%m/%d %H:%M'),
                (log.user.username if log.user else 'System')[:15],
                log.get_action_display(),
                log.get_module_display(),
                log.description[:30],
            ])
        
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        elements.append(table)
        
        doc.build(elements)
        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="activity_log_report.pdf"'
        return response
    
    return export_activity_log(queryset, 'csv', request)