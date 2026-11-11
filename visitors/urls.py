from django.urls import path
from . import views

app_name = 'visitors'

urlpatterns = [
    path('checkout/<int:visitor_id>/', views.checkout_visitor, name='checkout'),
    path('pre-register/', views.pre_register_visitor, name='pre_register'),
    path('pre-register/list/', views.pre_registration_list, name='pre_registration_list'),
    path('pre-register/<uuid:unique_link>/', views.pre_register_form, name='pre_register_form'),
    path('pre-register/verify/<int:pre_registration_id>/', views.verify_pre_registration, name='verify_pre_registration'),
    path('verify/', views.verify_visitor, name='verify'),
    path('print/<int:visitor_id>/', views.print_visitor_pass, name='print_pass'),
    path('bulk-checkout/', views.bulk_checkout, name='bulk_checkout'),
    path('delete/<int:visitor_id>/', views.delete_visitor, name='delete_visitor'),
    path('bulk-delete/', views.bulk_delete_visitors, name='bulk_delete'),
    # Live lookup for auto-fill
    path('lookup/', views.lookup_visitor, name='lookup_visitor'),
    # ALPR Scan Plate API
    path('api/scan-plate/', views.scan_plate_api, name='scan_plate_api'),
    # ALPR Whitelist Management APIs
    path('api/whitelist/add/', views.whitelist_plate_api, name='whitelist_plate_api'),
    path('api/whitelist/remove/', views.remove_whitelist_api, name='remove_whitelist_api'),
    path('api/whitelist/status/', views.whitelist_status_api, name='whitelist_status_api'),
    # ALPR Whitelist Management Interface
    path('whitelist/', views.whitelist_management, name='whitelist_management'),
    # Self Registration
    path('self-register/', views.self_register, name='self_register'),
    path('self-register/photo/<str:pass_number>/', views.self_register_photo, name='self_register_photo'),
    path('self-register/success/<str:pass_number>/', views.self_register_success, name='self_register_success'),
    # Self Checkout
    path('self-checkout/', views.self_checkout, name='self_checkout'),
    # Face upload API for self-register step
    path('api/self-register/upload-face/', views.self_register_upload_face_api, name='self_register_upload_face_api'),
    # Photo validation API (no upload to terminal)
    path('api/self-register/validate-photo/', views.validate_photo_api, name='validate_photo_api'),
]