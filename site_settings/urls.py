from django.urls import path
from . import views

app_name = 'site_settings'

urlpatterns = [
    # Main Settings Dashboard
    path('', views.settings_dashboard, name='settings_dashboard'),
    
    # Site Management
    path('site-configuration/', views.site_configuration, name='site_configuration'),
    path('sites/', views.site_list, name='site_list'),
    path('sites/add/', views.site_add, name='site_add'),
    path('sites/<int:site_id>/edit/', views.site_edit, name='site_edit'),
    path('sites/<int:site_id>/delete/', views.site_delete, name='site_delete'),
    
    # Form Field Management
    path('form-fields/', views.form_fields_management, name='form_fields_management'),
    path('form-fields/update/', views.update_form_fields, name='update_form_fields'),
    path('form-fields/update-address-options/', views.update_address_options, name='update_address_options'),
    
    # Category Management
    path('categories/', views.category_list, name='category_list'),
    path('categories/add/', views.category_add, name='category_add'),
    path('categories/<int:category_id>/edit/', views.category_edit, name='category_edit'),
    path('categories/<int:category_id>/delete/', views.category_delete, name='category_delete'),

    # Auto Backup & Recovery
    path('backup/', views.backup_settings, name='backup_settings'),
    path('backup/download/', views.download_backup, name='download_backup'),
    
    # ALPR Whitelist Management
    path('alpr-whitelist/', views.alpr_whitelist, name='alpr_whitelist'),
]