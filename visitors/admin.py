from django.contrib import admin
from .models import Visitor, PreRegistration, ALPRWhitelist

class PreRegistrationInline(admin.StackedInline):
    model = PreRegistration
    can_delete = False
    readonly_fields = ('unique_link', 'otp', 'qr_code')
    verbose_name_plural = 'Pre-Registration Details'

@admin.register(Visitor)
class VisitorAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'pass_number', 'category', 'check_in_time', 'check_out_time', 'is_pre_registered')
    list_filter = ('category', 'is_pre_registered', 'check_in_time')
    search_fields = ('full_name', 'pass_number', 'ic_last_digits', 'contact_number')
    readonly_fields = ('pass_number',)
    inlines = [PreRegistrationInline]
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # No site filtering needed in single-site setup
        return qs


@admin.register(ALPRWhitelist)
class ALPRWhitelistAdmin(admin.ModelAdmin):
    list_display = ('plate_number', 'visitor_name', 'is_active', 'is_expired', 'synced_to_camera', 'whitelisted_at', 'expires_at', 'created_by')
    list_filter = ('is_active', 'synced_to_camera', 'whitelisted_at', 'expires_at')
    search_fields = ('plate_number', 'visitor__full_name', 'visitor__company', 'created_by__username')
    readonly_fields = ('whitelisted_at', 'sync_attempts', 'is_expired')
    ordering = ('-whitelisted_at',)
    
    def visitor_name(self, obj):
        return obj.visitor.full_name if obj.visitor else 'Manual Entry'
    visitor_name.short_description = 'Visitor'
    
    def is_expired(self, obj):
        return obj.is_expired
    is_expired.boolean = True
    is_expired.short_description = 'Expired'
    
    fieldsets = (
        ('Whitelist Information', {
            'fields': ('visitor', 'plate_number', 'is_active')
        }),
        ('Timing', {
            'fields': ('whitelisted_at', 'expires_at')
        }),
        ('Camera Synchronization', {
            'fields': ('synced_to_camera', 'sync_attempts', 'sync_error'),
            'description': 'Camera synchronization status and error details'
        }),
        ('Metadata', {
            'fields': ('created_by',),
            'classes': ('collapse',)
        })
    )

@admin.register(PreRegistration)
class PreRegistrationAdmin(admin.ModelAdmin):
    list_display = ('visitor', 'registered_by', 'is_used', 'is_expired', 'expires_at')
    list_filter = ('is_used', 'expires_at')
    readonly_fields = ('unique_link', 'otp', 'qr_code')
    search_fields = ('visitor__full_name', 'visitor__pass_number', 'otp')
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # No site filtering needed in single-site setup
        return qs
