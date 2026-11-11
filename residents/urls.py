from django.urls import path
from . import views

app_name = 'residents'

urlpatterns = [
    path('management/', views.management, name='management'),
    path('bulk-operations/', views.bulk_operations, name='bulk_operations'),
    path('bulk-upload/', views.bulk_upload_vehicles, name='bulk_upload'),
    path('bulk-upload/template/', views.download_bulk_upload_template, name='bulk_upload_template'),
    path('export/residents/', views.export_residents, name='export_residents'),
    path('export/vehicles/', views.export_vehicles, name='export_vehicles'),
    path('export/vehicles/pdf/', views.export_vehicles_pdf, name='export_vehicles_pdf'),
    path('api/vehicle-log/', views.resident_vehicle_log_api, name='vehicle_log_api'),
    path('api/recent-logs/', views.get_recent_resident_logs, name='recent_logs_api'),
    path('api/vehicle-remarks/', views.update_vehicle_remarks, name='update_vehicle_remarks'),
    path('api/vehicle-sync/', views.sync_vehicle_to_camera, name='sync_vehicle_to_camera'),
    path('api/vehicle-sync-all/', views.sync_all_vehicles_to_camera, name='sync_all_vehicles_to_camera'),
]
