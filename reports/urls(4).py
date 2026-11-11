from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    path('', views.reports_dashboard, name='dashboard'),
    path('visitors/', views.visitor_report, name='visitor_report'),
    path('vehicles/', views.vehicle_report, name='vehicle_report'),
    path('pre-registrations/', views.pre_registration_reports, name='pre_registration_reports'),
    path('analytics/', views.analytics_report, name='analytics'),
    path('resident-history/', views.resident_history_report, name='resident_history_report'),
    path('activity-log/', views.activity_log_report, name='activity_log_report'),
    path('export/csv/', views.export_visitors_csv, name='export_csv'),
    path('export/excel/', views.export_visitors_excel, name='export_excel'),
    path('export/pdf/', views.export_visitors_pdf, name='export_pdf'),
    # API endpoints for consolidated reports
    path('api/visitor/<int:visitor_id>/', views.visitor_detail_api, name='visitor_detail_api'),
    path('api/visitor/<int:visitor_id>/full/', views.visitor_detail_full_api, name='visitor_detail_full_api'),
    path('api/visitor/<int:visitor_id>/checkout/', views.visitor_checkout_api, name='visitor_checkout_api'),
    path('api/visitor/<int:visitor_id>/edit/', views.visitor_edit_api, name='visitor_edit_api'),
    path('api/verify-password/', views.verify_password_api, name='verify_password_api'),
]