from datetime import time

from django.contrib.auth.models import User
from django.db import models


class Site(models.Model):
    name = models.CharField(max_length=100)
    address = models.TextField()
    postal_code = models.CharField(max_length=10, blank=True, null=True)
    contact_number = models.CharField(max_length=20)
    email = models.EmailField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class SiteLogo(models.Model):
    site = models.OneToOneField(Site, on_delete=models.CASCADE, related_name="logo")
    logo_light = models.ImageField(
        upload_to="logos/", blank=True, null=True, help_text="Logo for light theme"
    )
    logo_dark = models.ImageField(
        upload_to="logos/", blank=True, null=True, help_text="Logo for dark theme"
    )
    alt_text = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Logo for {self.site.name}"

    @property
    def display_logo_light(self):
        """Return light theme logo or fallback"""
        if self.logo_light:
            return self.logo_light.url
        return None

    @property
    def display_logo_dark(self):
        """Return dark theme logo or fallback"""
        if self.logo_dark:
            return self.logo_dark.url
        return self.site.name

    class Meta:
        verbose_name = "Site Logo"
        verbose_name_plural = "Site Logos"


class FormFieldConfiguration(models.Model):
    """Configuration for visitor registration form fields"""

    FIELD_TYPES = [
        ("text", "Text Input"),
        ("number", "Number Input"),
        ("select", "Dropdown Select"),
        ("textarea", "Text Area"),
        ("datetime", "Date Time"),
        ("hidden", "Hidden Field"),
    ]

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="form_fields")
    field_name = models.CharField(max_length=50)
    field_label = models.CharField(max_length=100)
    field_type = models.CharField(max_length=20, choices=FIELD_TYPES, default="text")
    is_required = models.BooleanField(default=False)
    is_enabled = models.BooleanField(default=True)
    placeholder_text = models.CharField(max_length=100, blank=True)
    help_text = models.CharField(max_length=200, blank=True)
    field_order = models.PositiveIntegerField(default=0)
    options = models.JSONField(
        default=list, blank=True, help_text="For select fields, provide list of options"
    )
    validation_rules = models.JSONField(
        default=dict, blank=True, help_text="Additional validation rules"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Form Field Configuration"
        verbose_name_plural = "Form Field Configurations"
        ordering = ["field_order", "field_name"]
        unique_together = ["site", "field_name"]

    def __str__(self):
        return f"{self.site.name} - {self.field_label}"


class AddressConfiguration(models.Model):
    """Configuration for address fields (Tower, Level, Unit)"""

    site = models.OneToOneField(
        Site, on_delete=models.CASCADE, related_name="address_config"
    )

    # Tower configuration
    enable_tower = models.BooleanField(default=True)
    tower_label = models.CharField(max_length=50, default="Tower")
    tower_options = models.JSONField(default=list, help_text="List of available towers")

    # Level configuration
    enable_level = models.BooleanField(default=True)
    level_label = models.CharField(max_length=50, default="Level")
    level_options = models.JSONField(default=list, help_text="List of available levels")

    # Unit configuration
    enable_unit = models.BooleanField(default=True)
    unit_label = models.CharField(max_length=50, default="Unit")
    unit_options = models.JSONField(default=list, help_text="List of available units")
    
    # Address mode: 'address_fields' or 'area_of_visit'
    address_mode = models.CharField(
        max_length=20,
        choices=[('address_fields', 'Address Fields'), ('area_of_visit', 'Area of Visit')],
        default='address_fields',
        help_text="Choose between address fields (Tower/Level/Unit) or Area of Visit dropdown"
    )
    area_of_visit_options = models.JSONField(
        default=list,
        blank=True,
        help_text="List of available areas for Area of Visit dropdown"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Address Config for {self.site.name}"

    @classmethod
    def get_or_create_for_site(cls, site):
        """Get or create address configuration for a site with defaults"""
        config, created = cls.objects.get_or_create(
            site=site,
            defaults={
                "tower_options": [f"Tower {i}" for i in range(1, 11)],
                "level_options": [f"Level {i}" for i in range(1, 6)],
                "unit_options": [f"Unit {i}" for i in range(1, 6)],
            },
        )
        return config

    class Meta:
        verbose_name = "Address Configuration"
        verbose_name_plural = "Address Configurations"


class SiteConfiguration(models.Model):
    site = models.OneToOneField(
        Site, on_delete=models.CASCADE, related_name="configuration"
    )
    logo = models.ImageField(upload_to="logos/", null=True, blank=True)
    enable_dark_mode = models.BooleanField(default=True)
    default_language = models.CharField(
        max_length=10,
        choices=[("en", "English"), ("zh", "Mandarin"), ("ms", "Malay")],
        default="en",
    )
    # Form field configurations
    enable_ic_number = models.BooleanField(default=True)
    enable_vehicle_number = models.BooleanField(default=True)
    enable_company = models.BooleanField(default=True)
    enable_address = models.BooleanField(default=True)
    enable_purpose = models.BooleanField(default=True)

    # Address configuration
    available_towers = models.CharField(max_length=255, default="1,2,3,4,5,6,7,8,9,10")
    available_levels = models.CharField(max_length=255, default="1,2,3,4,5")
    available_units = models.CharField(max_length=255, default="1,2,3,4,5")

    # Visitor form field configuration
    visitor_fields_config = models.JSONField(
        default=dict,
        help_text="Configuration for visitor form fields visibility and requirements",
    )

    # Pre-registration and verification settings
    enable_pre_registration = models.BooleanField(default=True)
    enable_qr_code = models.BooleanField(default=True)
    enable_otp = models.BooleanField(default=True)

    # Feature toggles (per site)
    enable_alpr_whitelist = models.BooleanField(default=False, help_text="Tampilkan & aktifkan ALPR Whitelist")
    enable_resident_management = models.BooleanField(default=False, help_text="Tampilkan & aktifkan Resident Management")
    enable_face_capture = models.BooleanField(
        default=True,
        help_text="Enable/disable face photo capture during self-registration. If disabled, visitors skip the selfie step."
    )

    # Printer settings
    enable_printer = models.BooleanField(
        default=True, help_text="Enable/disable automatic printing of visitor passes"
    )

    # Door/Gate control button visibility settings
    enable_side_door_button = models.BooleanField(
        default=True, help_text="Show/hide Side Door button on dashboard for all users"
    )
    enable_gate_button = models.BooleanField(
        default=True, help_text="Show/hide Gate button on dashboard for all users"
    )
    enable_auto_gate_on_checkin = models.BooleanField(
        default=False, help_text="Automatically open gate when visitor checks in and plate is whitelisted"
    )

    # Print slip format selection
    PRINT_SLIP_CHOICES = [
        ("0", "Full Pass with QR (Default)"),
        ("1", "Print Slip 1 (Compact)"),
        ("2", "Print Slip 2 (EU Habitat)"),
    ]
    print_slip_format = models.CharField(
        max_length=10,
        choices=PRINT_SLIP_CHOICES,
        default="0",
        help_text="Select which print slip format to use for visitor passes"
    )

    # CSS Theme Mode - CDN (default) or Local CSS for offline use
    use_local_css = models.BooleanField(
        default=False,
        help_text="Use locally compiled CSS instead of CDN. Enable for offline/intranet deployments."
    )

    # Auto backup settings (Option A - OS scheduler based)
    enable_auto_backup = models.BooleanField(
        default=False, help_text="Use OS scheduler to trigger backups. Default is OFF."
    )
    backup_output_dir = models.CharField(
        max_length=255, default="backups", help_text="Directory to store backup files"
    )
    backup_frequency = models.CharField(
        max_length=20,
        choices=[("daily", "Daily"), ("weekly", "Weekly"), ("monthly", "Monthly")],
        default="daily",
        help_text="Preferred schedule for external scheduler",
    )
    backup_time = models.TimeField(
        default=time(2, 0),
        help_text="Preferred time for backups (used by external scheduler)",
    )
    backup_keep_days = models.PositiveIntegerField(
        default=30, help_text="Days to keep backup files before cleanup"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Configuration for {self.site.name}"

    def get_towers_list(self):
        return self.available_towers.split(",")

    def get_levels_list(self):
        return self.available_levels.split(",")

    def get_units_list(self):
        return self.available_units.split(",")


class VisitorCategory(models.Model):
    name = models.CharField(max_length=50)
    site = models.ForeignKey(
        Site, on_delete=models.CASCADE, related_name="visitor_categories"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Visitor Categories"


class HikvisionConfiguration(models.Model):
    """Configuration for Hikvision Face Reader Terminal integration"""

    site = models.OneToOneField(
        Site, on_delete=models.CASCADE, related_name="hikvision_config"
    )

    # Terminal connection settings
    terminal_ip = models.GenericIPAddressField(
        default="192.168.1.100",
        help_text="IP address of the Hikvision Face Reader Terminal",
    )
    terminal_port = models.PositiveIntegerField(
        default=80,
        help_text="Port number for the terminal (usually 80 for HTTP or 443 for HTTPS)",
    )
    use_https = models.BooleanField(
        default=False, help_text="Use HTTPS instead of HTTP for secure connection"
    )

    # Authentication settings
    username = models.CharField(
        max_length=100, default="admin", help_text="Username for Digest authentication"
    )
    password = models.CharField(
        max_length=100, help_text="Password for Digest authentication"
    )

    # Door control settings
    default_door_number = models.PositiveIntegerField(
        default=1, help_text="Default door number to control (usually 1)"
    )

    # Connection settings
    timeout_seconds = models.PositiveIntegerField(
        default=10, help_text="Connection timeout in seconds"
    )

    # Feature toggles
    is_enabled = models.BooleanField(
        default=True, help_text="Enable/disable Hikvision terminal integration"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Hikvision Config for {self.site.name} ({self.terminal_ip})"

    @property
    def terminal_url(self):
        """Get the full terminal URL"""
        protocol = "https" if self.use_https else "http"
        port_suffix = (
            f":{self.terminal_port}"
            if self.terminal_port != (443 if self.use_https else 80)
            else ""
        )
        return f"{protocol}://{self.terminal_ip}{port_suffix}"

    @property
    def door_control_endpoint(self):
        """Get the door control API endpoint"""
        return f"{self.terminal_url}/ISAPI/AccessControl/RemoteControl/door/{self.default_door_number}"

    @classmethod
    def get_or_create_for_site(cls, site):
        """Get or create Hikvision configuration for a site"""
        config, created = cls.objects.get_or_create(
            site=site,
            defaults={
                "terminal_ip": "192.168.1.100",
                "username": "admin",
                "password": "",
                "is_enabled": False,  # Disabled by default until configured
            },
        )
        return config

    class Meta:
        verbose_name = "Hikvision Configuration"
        verbose_name_plural = "Hikvision Configurations"


class DahuaConfiguration(models.Model):
    """Configuration for Dahua ANPR camera"""

    site = models.OneToOneField(
        Site, on_delete=models.CASCADE, related_name="dahua_config"
    )

    # Primary (general) camera
    camera_ip = models.GenericIPAddressField(
        default=None,
        blank=True,
        null=True,
        help_text="IP address of the Dahua ANPR Camera",
    )
    camera_port = models.PositiveIntegerField(
        default=80,
        help_text="Port number for the camera (usually 80 for HTTP or 443 for HTTPS)",
    )
    use_https = models.BooleanField(
        default=False, help_text="Use HTTPS instead of HTTP for secure connection"
    )
    username = models.CharField(
        max_length=100, default="admin", help_text="Username for Digest authentication"
    )
    password = models.CharField(
        max_length=100, help_text="Password for Digest authentication"
    )

    # Visitor Out camera (for auto-checkout)
    visitor_out_camera_ip = models.GenericIPAddressField(
        default=None,
        blank=True,
        null=True,
        help_text="IP address of the Visitor Out Dahua ANPR Camera (for auto-checkout)",
    )
    visitor_out_camera_port = models.PositiveIntegerField(
        default=80, help_text="Port number for the visitor out camera"
    )
    visitor_out_use_https = models.BooleanField(
        default=False, help_text="Use HTTPS for visitor out camera"
    )
    visitor_out_username = models.CharField(
        max_length=100,
        default="admin",
        help_text="Username for Digest authentication (visitor out camera)",
    )
    visitor_out_password = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Password for Digest authentication (visitor out camera)"
    )
    visitor_out_is_enabled = models.BooleanField(
        default=False, help_text="Enable/disable Visitor Out camera integration for auto-checkout"
    )

    # Resident-specific camera
    resident_camera_ip = models.GenericIPAddressField(
        default="192.168.1.221",
        help_text="IP address of the Resident Dahua ANPR Camera",
    )
    resident_camera_port = models.PositiveIntegerField(
        default=80, help_text="Port number for the resident camera"
    )
    resident_use_https = models.BooleanField(
        default=False, help_text="Use HTTPS for resident camera"
    )
    resident_username = models.CharField(
        max_length=100,
        default="admin",
        help_text="Username for Digest authentication (resident camera)",
    )
    resident_password = models.CharField(
        max_length=100, help_text="Password for Digest authentication (resident camera)"
    )
    resident_is_enabled = models.BooleanField(
        default=False, help_text="Enable/disable Resident camera integration"
    )

    # Gate control settings
    default_channel = models.PositiveIntegerField(
        default=1, help_text="Default channel number to control (usually 1)"
    )

    # Capture settings (reverted: remove ANPR mode selection)

    # Connection settings
    timeout_seconds = models.PositiveIntegerField(
        default=10, help_text="Connection timeout in seconds"
    )

    # Feature toggles
    is_enabled = models.BooleanField(
        default=True, help_text="Enable/disable Dahua ANPR Camera integration"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Dahua ANPR Config for {self.site.name} ({self.camera_ip})"

    @property
    def camera_url(self):
        """Get the full camera URL"""
        protocol = "https" if self.use_https else "http"
        port_suffix = (
            f":{self.camera_port}"
            if self.camera_port != (443 if self.use_https else 80)
            else ""
        )
        return f"{protocol}://{self.camera_ip}{port_suffix}"

    @property
    def resident_camera_url(self):
        """Get the full resident camera URL"""
        protocol = "https" if self.resident_use_https else "http"
        port_suffix = (
            f":{self.resident_camera_port}"
            if self.resident_camera_port != (443 if self.resident_use_https else 80)
            else ""
        )
        return f"{protocol}://{self.resident_camera_ip}{port_suffix}"

    @property
    def visitor_out_camera_url(self):
        """Get the full visitor out camera URL"""
        if not self.visitor_out_camera_ip:
            return None
        protocol = "https" if self.visitor_out_use_https else "http"
        port_suffix = (
            f":{self.visitor_out_camera_port}"
            if self.visitor_out_camera_port != (443 if self.visitor_out_use_https else 80)
            else ""
        )
        return f"{protocol}://{self.visitor_out_camera_ip}{port_suffix}"

    @property
    def gate_control_endpoint(self):
        """Get the gate control API endpoint"""
        return f"{self.camera_url}/cgi-bin/accessControl.cgi"

    @classmethod
    def get_or_create_for_site(cls, site):
        """Get or create Dahua configuration for a site"""
        config, created = cls.objects.get_or_create(
            site=site,
            defaults={
                "camera_ip": "192.168.227.100",
                "username": "admin",
                "password": "",
                "is_enabled": False,  # Disabled by default until configured
                "resident_camera_ip": "192.168.1.221",
                "resident_is_enabled": False,
            },
        )
        return config

    class Meta:
        verbose_name = "Dahua ANPR Configuration"
        verbose_name_plural = "Dahua ANPR Configurations"
