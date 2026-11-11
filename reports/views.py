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
import os

from visitors.models import Visitor, PreRegistration, ALPRWhitelist, OccurrenceLog
from site_settings.models import Site, VisitorCategory
from accounts.decorators import can_view_reports
from django.contrib import messages
from django.core.paginator import Paginator

# Install required packages for Excel and PDF export
try:
    import openpyxl
    from openpyxl.styles import Font, Alignment
except ImportError:
    openpyxl = None

try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.lib.utils import ImageReader
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.charts.piecharts import Pie
except ImportError:
    SimpleDocTemplate = None

@login_required
@can_view_reports
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
@can_view_reports
def visitor_report(request):
    """Generate consolidated visitor reports with smart search and filters"""
    user_profile = request.user.profile
    export_format = request.GET.get('export')
    
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
    # Page size control (default 50)
    try:
        page_size = int(request.GET.get('page_size', 50))
    except (TypeError, ValueError):
        page_size = 50
    if page_size not in (10, 50, 100):
        page_size = 50
    
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
    
    # Overtime filter
    overtime = request.GET.get('overtime')
    today = timezone.now().date() if timezone.is_naive(timezone.now()) else timezone.now().date()
    if overtime == 'all_overtime':
        # Visitors whose check_in_time date is before today (stayed past midnight)
        visitors = visitors.filter(check_in_time__date__lt=today, check_out_time__isnull=True)
    elif overtime == 'overtime_only':
        # Same as above but specifically for delivery category if it exists
        visitors = visitors.filter(check_in_time__date__lt=today, check_out_time__isnull=True)
    
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
    if export_format:
        # If specific visitor IDs are selected, restrict export to those
        selected = request.GET.get('visitors')
        if selected:
            try:
                id_list = [int(x) for x in selected.split(',') if x.isdigit()]
                if id_list:
                    visitors = visitors.filter(id__in=id_list)
            except Exception:
                pass
        return export_visitor_data(visitors, export_format, request)
    
    # Pagination
    from django.core.paginator import Paginator
    paginator = Paginator(visitors, page_size)
    
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
            'category': category_id,
            'date_from': date_from,
            'date_to': date_to,
            'status': status,
            'search': search,
            'sort': sort_by,
            'page_size': page_size,
            'overtime': overtime,
        },
        'total_count': total_count,
    }
    
    return render(request, 'reports/visitor_report.html', context)


from reportlab.platypus import KeepTogether, PageBreak

def build_professional_pdf_header(site, title_text, subtitle_text):
    elements = []
    styles = getSampleStyleSheet()
    
    # Custom Styles
    title_style = ParagraphStyle('ReportTitle', parent=styles['Heading1'], fontSize=16, textColor=colors.HexColor('#1E3A8A'), spaceAfter=2)
    subtitle_style = ParagraphStyle('ReportSubtitle', parent=styles['Normal'], fontSize=10, textColor=colors.gray, spaceAfter=20)
    site_name_style = ParagraphStyle('SiteName', parent=styles['Heading2'], fontSize=12, textColor=colors.black, spaceAfter=2)
    address_style = ParagraphStyle('Address', parent=styles['Normal'], fontSize=9, textColor=colors.dimgray, spaceAfter=2)
    
    header_data = []
    
    logo_img = None
    if site:
        logo_path = None
        from django.conf import settings as django_settings
        preferred_logo = os.path.join(django_settings.MEDIA_ROOT, 'logos', 'sctlogo-s-DarkBlue.png')
        try:
            if os.path.exists(preferred_logo):
                logo_path = preferred_logo
            elif getattr(site, 'logo', None):
                if hasattr(site.logo, 'logo_dark') and site.logo.logo_dark:
                    logo_path = site.logo.logo_dark.path
                elif hasattr(site.logo, 'logo_light') and site.logo.logo_light:
                    logo_path = site.logo.logo_light.path
                elif hasattr(site.logo, 'path'):
                    logo_path = site.logo.path
            
            if logo_path and os.path.exists(logo_path):
                # Proportional logo
                logo_img = Image(logo_path, width=1.4*inch, height=1.4*inch)
                logo_img.hAlign = 'LEFT'
        except Exception:
            pass
            
    site_info = []
    if site:
        site_info.append(Paragraph(site.name, site_name_style))
        if getattr(site, 'address', None):
            site_info.append(Paragraph(site.address, address_style))
        if getattr(site, 'postal_code', None):
            site_info.append(Paragraph(f"Singapore {site.postal_code}", address_style))
    else:
        site_info.append(Paragraph("System Report", site_name_style))
    # Layout: Logo → Site Info → Report Title (all stacked vertically, left-aligned)
    if logo_img:
        elements.append(logo_img)
    
    if site:
        elements.append(Paragraph(site.name, site_name_style))
        if getattr(site, 'address', None):
            elements.append(Paragraph(site.address, address_style))
        if getattr(site, 'postal_code', None):
            elements.append(Paragraph(f"Singapore {site.postal_code}", address_style))
    else:
        elements.append(Paragraph("System Report", site_name_style))
        
    elements.append(Spacer(1, 15))
    elements.append(Paragraph(title_text, title_style))
    elements.append(Paragraph(subtitle_text, subtitle_style))
    elements.append(Spacer(1, 15))
    return elements


def export_visitor_data(visitors, format_type, request):
    """Export visitor data in various formats"""
    filename = f'visitor_report_{timezone.now().strftime("%Y%m%d_%H%M%S")}'
    
    if format_type == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'Full Name', 'Contact Number', 'Company', 'Category', 
            'Check-in Time', 'Check-out Time', 'Pass Number', 'Vehicle Number',
            'Purpose', 'IC Last Digits', 'Status', 'Duration'
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
                visitor.purpose or '',
                visitor.ic_last_digits or '',
                'Checked Out' if visitor.check_out_time else 'Active',
                duration
            ])
        
        return response
    
    elif format_type == 'excel' and openpyxl:
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="{filename}.xlsx"'
        
        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.title = 'Visitor Report'
        
        # Header
        headers = [
            'Full Name', 'Contact Number', 'Company', 'Category', 
            'Check-in Time', 'Check-out Time', 'Pass Number', 'Vehicle Number',
            'Purpose', 'IC Last Digits', 'Status', 'Duration'
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
                visitor.purpose or '',
                visitor.ic_last_digits or '',
                'Checked Out' if visitor.check_out_time else 'Active',
                duration
            ]
            
            for col, value in enumerate(data, 1):
                worksheet.cell(row=row, column=col, value=value)
        
        workbook.save(response)
        return response
    
    elif format_type == 'pdf' and SimpleDocTemplate:
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}.pdf"'
        
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=48,
            rightMargin=48,
            topMargin=24,
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
        
        date_str = ""
        if date_from and date_to:
            date_str = f"{date_from} to {date_to}"
        elif date_from:
            date_str = f"From {date_from}"
        elif date_to:
            date_str = f"Until {date_to}"
        else:
            date_str = "All Time"
        
        elements = build_professional_pdf_header(primary_site, 'Visitor Report', date_str)
        styles = getSampleStyleSheet()
        
        # Detailed visitor table matching current filters
        try:
            elements.append(Paragraph('Visitor Details', styles['Heading3']))
            table_headers = [
                'Full Name', 'Company', 'Category', 'Check-in', 'Check-out', 'Status', 'Duration'
            ]
            table_data = [table_headers]
            for v in visitors:
                duration = ''
                status = 'Checked Out' if v.check_out_time else 'Active'
                if v.check_out_time:
                    duration = str(v.check_out_time - v.check_in_time)
                else:
                    duration = str(timezone.now() - v.check_in_time)
                table_data.append([
                    v.full_name,
                    v.company or '',
                    (v.category.name if v.category else ''),
                    timezone.localtime(v.check_in_time).strftime('%Y-%m-%d %H:%M'),
                    timezone.localtime(v.check_out_time).strftime('%Y-%m-%d %H:%M') if v.check_out_time else '',
                    status,
                    duration,
                ])
            v_table = Table(table_data, repeatRows=1)
            v_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.black)
            ]))
            elements.append(v_table)
            elements.append(Spacer(1, 10))
        except Exception:
            # If any unexpected rendering error, continue building the report without table
            elements.append(Paragraph('Visitor details unavailable.', styles['Italic']))
            elements.append(Spacer(1, 8))


        
        # Footer callback for page numbers
        def _footer(canvas, _doc):
            try:
                canvas.saveState()
                canvas.setFont('Helvetica', 8)
                canvas.setFillColor(colors.grey)
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
@can_view_reports
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
@can_view_reports
def export_visitors_csv(request):
    """Export visitors with current filters to CSV."""
    visitors = _filtered_visitors_queryset(request)
    return export_visitor_data(visitors, 'csv', request)


@login_required
@can_view_reports
def export_visitors_excel(request):
    """Export visitors with current filters to Excel."""
    visitors = _filtered_visitors_queryset(request)
    return export_visitor_data(visitors, 'excel', request)


@login_required
@can_view_reports
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

    # If specific IDs provided (from bulk selection), restrict to them
    selected = request.GET.get('visitors')
    if selected:
        try:
            id_list = [int(x) for x in selected.split(',') if x.isdigit()]
            if id_list:
                visitors = visitors.filter(id__in=id_list)
        except Exception:
            pass

    return visitors.select_related('category')


@login_required
@can_view_reports
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
@can_view_reports
def visitor_detail_full_api(request, visitor_id):
    """Return extended visitor details as JSON."""
    visitor = get_object_or_404(Visitor, id=visitor_id)
    data = {
        'id': visitor.id,
        'full_name': visitor.full_name,
        'company': visitor.company or '',
        'contact_number': visitor.contact_number or '',
        'category': visitor.category.name if visitor.category else None,
        'check_in_time': timezone.localtime(visitor.check_in_time).strftime('%Y-%m-%d %H:%M') if visitor.check_in_time else None,
        'check_out_time': timezone.localtime(visitor.check_out_time).strftime('%Y-%m-%d %H:%M') if visitor.check_out_time else None,
        'pass_number': visitor.pass_number or '',
        'vehicle_number': visitor.vehicle_number or '',
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
@can_view_reports
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
@can_view_reports
@require_POST
def verify_password_api(request):
    """Verify the current user's password. Expects 'password' in POST."""
    password = request.POST.get('password', '')
    ok = request.user.check_password(password) if password else False
    return JsonResponse({'success': ok})


@login_required
@can_view_reports
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

    return JsonResponse({
        'success': True,
        'message': f'Visitor updated successfully. Fields updated: {", ".join(updated_fields)}' if updated_fields else 'No changes made.',
        'updated_fields': updated_fields
    })
# ========================================================
# OCCURRENCE REPORTS & EXPORTS
# ========================================================

@login_required
@can_view_reports
def occurrence_report(request):
    """Occurrence Report view with filtering"""
    occurrences = OccurrenceLog.objects.select_related('created_by').all()
    
    # Get filters
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    category = request.GET.get('category')
    severity = request.GET.get('severity')
    search = request.GET.get('search')
    
    # Apply filters
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            occurrences = occurrences.filter(created_at__date__gte=date_from_obj)
        except ValueError:
            pass
            
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            occurrences = occurrences.filter(created_at__date__lte=date_to_obj)
        except ValueError:
            pass
            
    if category:
        occurrences = occurrences.filter(category=category)
        
    if severity:
        occurrences = occurrences.filter(severity=severity)
        
    if search:
        occurrences = occurrences.filter(
            Q(title__icontains=search) |
            Q(description__icontains=search) |
            Q(officer_name__icontains=search) |
            Q(location__icontains=search)
        )
        
    occurrences = occurrences.order_by('-created_at')
    
    # Pagination
    try:
        page_size = int(request.GET.get('page_size', 50))
    except ValueError:
        page_size = 50
        
    paginator = Paginator(occurrences, page_size)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'filters': {
            'date_from': date_from,
            'date_to': date_to,
            'category': category,
            'severity': severity,
            'search': search,
            'page_size': page_size
        },
        'categories': OccurrenceLog.CATEGORY_CHOICES,
        'severities': OccurrenceLog.SEVERITY_CHOICES
    }
    
    return render(request, 'reports/occurrence_report.html', context)

def export_occurrence_data(occurrences, format_type, request):
    """Helper to export occurrence logs to CSV or Excel"""
    filename = f'occurrence_report_{timezone.now().strftime("%Y%m%d_%H%M%S")}'
    
    if format_type == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}.csv"'
        writer = csv.writer(response)
        
        writer.writerow([
            'Date & Time', 'Category', 'Severity', 'Location', 
            'Title', 'Description', 'Duty Officer', 'Logged By Account'
        ])
        
        for occ in occurrences:
            writer.writerow([
                timezone.localtime(occ.created_at).strftime('%Y-%m-%d %H:%M:%S'),
                occ.get_category_display(),
                occ.get_severity_display(),
                occ.location or '',
                occ.title or '',
                occ.description or '',
                occ.officer_name or '',
                occ.created_by.username if occ.created_by else 'System'
            ])
            
        return response
        
    elif format_type == 'excel' and openpyxl:
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="{filename}.xlsx"'
        
        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.title = 'Occurrence Logs'
        
        headers = [
            'Date & Time', 'Category', 'Severity', 'Location', 
            'Title', 'Description', 'Duty Officer', 'Logged By Account'
        ]
        
        for col, header in enumerate(headers, 1):
            cell = worksheet.cell(row=1, column=col, value=header)
            cell.font = Font(bold=True)
            
        for row, occ in enumerate(occurrences, 2):
            worksheet.cell(row=row, column=1, value=timezone.localtime(occ.created_at).strftime('%Y-%m-%d %H:%M:%S'))
            worksheet.cell(row=row, column=2, value=occ.get_category_display())
            worksheet.cell(row=row, column=3, value=occ.get_severity_display())
            worksheet.cell(row=row, column=4, value=occ.location or '')
            worksheet.cell(row=row, column=5, value=occ.title or '')
            worksheet.cell(row=row, column=6, value=occ.description or '')
            worksheet.cell(row=row, column=7, value=occ.officer_name or '')
            worksheet.cell(row=row, column=8, value=occ.created_by.username if occ.created_by else 'System')
            
        # Adjust column widths
        for column_cells in worksheet.columns:
            length = max(len(str(cell.value)) for cell in column_cells)
            worksheet.column_dimensions[column_cells[0].column_letter].width = min(length + 2, 50)
            
        workbook.save(response)
        return response

    elif format_type == 'pdf' and SimpleDocTemplate:
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}.pdf"'
        
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=36, rightMargin=36,
            topMargin=24, bottomMargin=36,
        )
        
        primary_site = Site.objects.filter(is_active=True).first()
        date_from = request.GET.get('date_from')
        date_to = request.GET.get('date_to')
        date_str = ""
        if date_from and date_to:
            date_str = f"{date_from} to {date_to}"
        elif date_from:
            date_str = f"From {date_from}"
        elif date_to:
            date_str = f"Until {date_to}"
        else:
            date_str = "All Time"
            
        elements = build_professional_pdf_header(primary_site, 'Daily Occurrence Book Report', date_str)
        styles = getSampleStyleSheet()
        
        # Table data
        data = [['Date & Time', 'Category', 'Severity', 'Location', 'Title', 'Duty Officer']]
        
        for occ in occurrences:
            dt_str = timezone.localtime(occ.created_at).strftime('%Y-%m-%d %H:%M')
            cat_str = occ.get_category_display()
            sev_str = occ.get_severity_display()
            data.append([
                Paragraph(dt_str, styles['Normal']),
                Paragraph(cat_str, styles['Normal']),
                Paragraph(sev_str, styles['Normal']),
                Paragraph(occ.location or '', styles['Normal']),
                Paragraph(occ.title or '', styles['Normal']),
                Paragraph(occ.officer_name or '', styles['Normal'])
            ])
            
        table = Table(data, colWidths=[80, 70, 60, 100, 150, 80])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#6B21A8')), # Purple header
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,0), 10),
            ('BOTTOMPADDING', (0,0), (-1,0), 12),
            ('BACKGROUND', (0,1), (-1,-1), colors.white),
            ('GRID', (0,0), (-1,-1), 1, colors.lightgrey),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ]))
        
        elements.append(table)
        
        # Footer callback for page numbers
        def _footer(canvas, _doc):
            try:
                canvas.saveState()
                canvas.setFont('Helvetica', 8)
                canvas.setFillColor(colors.grey)
                canvas.drawRightString(_doc.pagesize[0]-_doc.rightMargin, 0.5*inch, f"Page {_doc.page}")
                canvas.restoreState()
            except Exception:
                pass
                
        doc.build(elements, onFirstPage=_footer, onLaterPages=_footer)
        
        pdf = buffer.getvalue()
        buffer.close()
        response.write(pdf)
        return response
        
    return HttpResponse("Format not supported", status=400)

@login_required
@can_view_reports
def export_occurrences_csv(request):
    occurrences = OccurrenceLog.objects.select_related('created_by').all().order_by('-created_at')
    # Can apply filters here if needed
    return export_occurrence_data(occurrences, 'csv', request)

@login_required
@can_view_reports
def export_occurrences_excel(request):
    occurrences = OccurrenceLog.objects.select_related('created_by').all().order_by('-created_at')
    # Can apply filters here if needed
    return export_occurrence_data(occurrences, 'excel', request)

@login_required
@can_view_reports
def export_occurrences_pdf(request):
    occurrences = OccurrenceLog.objects.select_related('created_by').all().order_by('-created_at')
    # Can apply filters here if needed
    return export_occurrence_data(occurrences, 'pdf', request)
