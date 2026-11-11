from django.contrib import admin

from .models import (
    AddressConfiguration,
    DahuaConfiguration,
    FormFieldConfiguration,
    HikvisionConfiguration,
    Site,
    SiteConfiguration,
    SiteLogo,
    VisitorCategory,
)


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ["name", "address", "is_active", "created_at"]
    list_filter = ["is_active", "created_at"]
    search_fields = ["name", "address"]
    ordering = ["name"]


@admin.register(VisitorCategory)
class VisitorCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "site", "is_active", "created_at"]
    list_filter = ["site", "is_active", "created_at"]
    search_fields = ["name", "site__name"]
    ordering = ["site", "name"]


@admin.register(SiteLogo)
class SiteLogoAdmin(admin.ModelAdmin):
    list_display = ["site", "has_light_logo", "has_dark_logo", "alt_text", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["site__name", "alt_text"]

    def has_light_logo(self, obj):
        return bool(obj.logo_light)

    has_light_logo.boolean = True
    has_light_logo.short_description = "Light Logo"

    def has_dark_logo(self, obj):
        return bool(obj.logo_dark)

    has_dark_logo.boolean = True
    has_dark_logo.short_description = "Dark Logo"

    def get_readonly_fields(self, request, obj=None):
        if obj:  # editing an existing object
            return ["site"]
        return []


@admin.register(HikvisionConfiguration)
class HikvisionConfigurationAdmin(admin.ModelAdmin):
    list_display = ["site", "terminal_ip", "username", "is_enabled", "updated_at"]
    list_filter = ["is_enabled", "use_https", "updated_at"]
    search_fields = ["site__name", "terminal_ip", "username"]
    ordering = ["site"]

    fieldsets = (
        ("Site Configuration", {"fields": ("site", "is_enabled")}),
        (
            "Terminal Connection",
            {
                "fields": (
                    "terminal_ip",
                    "terminal_port",
                    "use_https",
                    "timeout_seconds",
                ),
                "description": "Configure the connection settings for your Hikvision Face Reader Terminal",
            },
        ),
        (
            "Authentication",
            {
                "fields": ("username", "password"),
                "description": "Digest authentication credentials for the terminal",
            },
        ),
        (
            "Door Control Settings",
            {
                "fields": ("default_door_number",),
                "description": "Default door number to control (usually 1)",
            },
        ),
        (
            "Connection Test",
            {
                "fields": (),
                "description": 'Use the "Test Connection" button below to verify your settings',
            },
        ),
    )

    def get_readonly_fields(self, request, obj=None):
        if obj:  # editing an existing object
            return ["site"]
        return []

    def save_model(self, request, obj, form, change):
        """Custom save to handle password encryption if needed"""
        super().save_model(request, obj, form, change)

    class Media:
        css = {"all": ("admin/css/hikvision_admin.css",)}
        js = ("admin/js/hikvision_admin.js",)


@admin.register(DahuaConfiguration)
class DahuaConfigurationAdmin(admin.ModelAdmin):
    list_display = [
        "site",
        "camera_ip",
        "is_enabled",
        "visitor_out_camera_ip",
        "visitor_out_is_enabled",
        "resident_camera_ip",
        "resident_is_enabled",
        "updated_at",
    ]
    list_filter = [
        "is_enabled",
        "use_https",
        "visitor_out_is_enabled",
        "resident_is_enabled",
        "resident_use_https",
        "updated_at",
    ]
    search_fields = [
        "site__name",
        "camera_ip",
        "username",
        "visitor_out_camera_ip",
        "resident_camera_ip",
        "resident_username",
    ]
    ordering = ["site"]

    fieldsets = (
        ("Site Configuration", {"fields": ("site",)}),
        (
            "Visitor Camera Connection (In)",
            {
                "fields": ("is_enabled", "camera_ip", "camera_port", "use_https"),
                "description": "Dahua ANPR Camera for Visitor entrance - used for check-in and plate scanning",
            },
        ),
        (
            "Visitor Camera Authentication (In)",
            {
                "fields": ("username", "password"),
                "description": "Digest authentication credentials for visitor entrance camera",
            },
        ),
        (
            "Advanced Settings",
            {
                "fields": ("timeout_seconds", "default_channel"),
                "classes": ("collapse",),
                "description": "Advanced camera settings (usually don't need to change)",
            },
        ),
        (
            "Visitor Camera Connection (Out)",
            {
                "fields": (
                    "visitor_out_is_enabled",
                    "visitor_out_camera_ip",
                    "visitor_out_camera_port",
                    "visitor_out_use_https",
                ),
                "description": "Dahua ANPR Camera for Visitor exit - used for automatic checkout",
            },
        ),
        (
            "Visitor Camera Authentication (Out)",
            {
                "fields": ("visitor_out_username", "visitor_out_password"),
                "description": "Digest authentication credentials for visitor exit camera",
            },
        ),
        (
            "Resident Camera Connection",
            {
                "fields": (
                    "resident_is_enabled",
                    "resident_camera_ip",
                    "resident_camera_port",
                    "resident_use_https",
                ),
                "description": "Optional dedicated ALPR camera for Residents",
            },
        ),
        (
            "Resident Camera Authentication",
            {
                "fields": ("resident_username", "resident_password"),
                "description": "Digest authentication credentials for resident camera",
            },
        ),
    )

    def get_readonly_fields(self, request, obj=None):
        if obj:  # editing an existing object
            return ["site"]
        return []

    def save_model(self, request, obj, form, change):
        """Custom save to handle password encryption if needed"""
        super().save_model(request, obj, form, change)


@admin.register(FormFieldConfiguration)
class FormFieldConfigurationAdmin(admin.ModelAdmin):
    list_display = [
        "field_label",
        "field_name",
        "site",
        "field_type",
        "is_required",
        "is_enabled",
        "field_order",
    ]
    list_filter = ["site", "field_type", "is_required", "is_enabled"]
    search_fields = ["field_name", "field_label", "site__name"]
    ordering = ["site", "field_order", "field_name"]

    fieldsets = (
        (
            "Basic Information",
            {"fields": ("site", "field_name", "field_label", "field_type")},
        ),
        ("Configuration", {"fields": ("is_required", "is_enabled", "field_order")}),
        ("Display Options", {"fields": ("placeholder_text", "help_text")}),
        (
            "Advanced Options",
            {"fields": ("options", "validation_rules"), "classes": ("collapse",)},
        ),
    )

    def get_readonly_fields(self, request, obj=None):
        if obj:  # editing an existing object
            return ["site", "field_name"]
        return []


@admin.register(AddressConfiguration)
class AddressConfigurationAdmin(admin.ModelAdmin):
    list_display = ["site", "enable_tower", "enable_level", "enable_unit", "updated_at"]
    list_filter = ["enable_tower", "enable_level", "enable_unit"]
    search_fields = ["site__name"]

    fieldsets = (
        (
            "Tower Configuration",
            {"fields": ("enable_tower", "tower_label", "tower_options")},
        ),
        (
            "Level Configuration",
            {"fields": ("enable_level", "level_label", "level_options")},
        ),
        (
            "Unit Configuration",
            {"fields": ("enable_unit", "unit_label", "unit_options")},
        ),
    )

    def get_readonly_fields(self, request, obj=None):
        if obj:  # editing an existing object
            return ["site"]
        return []


@admin.register(SiteConfiguration)
class SiteConfigurationAdmin(admin.ModelAdmin):
    list_display = [
        "site",
        "enable_gate_button",
        "enable_auto_gate_on_checkin",
        "enable_printer",
        "enable_pre_registration",
        "updated_at",
    ]
    list_filter = ["enable_gate_button", "enable_auto_gate_on_checkin", "enable_printer"]
    search_fields = ["site__name"]

    fieldsets = (
        ("Site", {"fields": ("site",)}),
        (
            "Form Fields",
            {
                "fields": (
                    "enable_ic_number",
                    "enable_vehicle_number",
                    "enable_company",
                    "enable_address",
                    "enable_purpose",
                ),
            },
        ),
        (
            "Pre-registration & Verification",
            {"fields": ("enable_pre_registration", "enable_qr_code", "enable_otp")},
        ),
        (
            "Printer Settings",
            {"fields": ("enable_printer", "print_slip_format")},
        ),
        (
            "Gate & Door Control",
            {
                "fields": (
                    "enable_side_door_button",
                    "enable_gate_button",
                    "enable_auto_gate_on_checkin",
                ),
                "description": "Control visibility of door/gate buttons and automatic gate opening behavior",
            },
        ),
        (
            "Backup Settings",
            {
                "fields": (
                    "enable_auto_backup",
                    "backup_output_dir",
                    "backup_frequency",
                    "backup_time",
                    "backup_keep_days",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ["site"]
        return []
