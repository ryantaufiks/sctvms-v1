from django.db import models
from django.conf import settings
from site_settings.models import VisitorCategory
import uuid
import random
import string

class Visitor(models.Model):
    category = models.ForeignKey(VisitorCategory, on_delete=models.SET_NULL, null=True, related_name='visitors')
    ic_last_digits = models.CharField(max_length=4, verbose_name="Last 4 digits of IC")
    full_name = models.CharField(max_length=100)
    contact_number = models.CharField(max_length=20)
    pass_number = models.CharField(max_length=10, blank=True, null=True)
    vehicle_number = models.CharField(max_length=20, blank=True, null=True)
    plate_image = models.ImageField(upload_to='plate_images/', blank=True, null=True, verbose_name="License Plate Image")
    company = models.CharField(max_length=100, blank=True, null=True)
    
    # Address details
    tower = models.CharField(max_length=10, blank=True, null=True)
    level = models.CharField(max_length=10, blank=True, null=True)
    unit = models.CharField(max_length=10, blank=True, null=True)
    area_of_visit = models.CharField(max_length=200, blank=True, null=True, verbose_name="Area of Visit")
    area_of_visit_remarks = models.CharField(max_length=200, blank=True, null=True, verbose_name="Area of Visit Remarks")
    
    purpose = models.TextField(blank=True, null=True)
    check_in_time = models.DateTimeField(null=True, blank=True)
    check_out_time = models.DateTimeField(blank=True, null=True)
    is_pre_registered = models.BooleanField(default=False)
    
    # NEW: Self-registration access credentials and face image
    access_pin = models.CharField(max_length=8, blank=True, null=True, help_text="PIN/Password for terminal access")
    face_image = models.ImageField(upload_to='face_images/', blank=True, null=True, help_text="Captured face image for terminal enrollment")
    terminal_user_id = models.CharField(max_length=64, blank=True, null=True, help_text="Terminal user identifier (employeeNo)")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.full_name} - {self.pass_number}"
    
    class Meta:
        indexes = [
            models.Index(fields=['check_in_time']),
            models.Index(fields=['check_out_time']),
            models.Index(fields=['category']),
            models.Index(fields=['is_pre_registered']),
            models.Index(fields=['pass_number']),
        ]
        ordering = ['-check_in_time']
    
    def save(self, *args, **kwargs):
        from django.utils import timezone
        
        # Set check_in_time for non-pre-registered visitors or verified pre-registered visitors
        if not self.check_in_time:
            if not self.is_pre_registered:
                self.check_in_time = timezone.now()
            elif self.is_pre_registered and hasattr(self, 'pre_registration') and self.pre_registration.is_verified:
                self.check_in_time = timezone.now()
        
        # Auto-generate pass number
        if not self.pass_number:
            if self.is_pre_registered:
                # Pre-registered visitors get PRxxxx immediately
                self.pass_number = self.generate_pre_registration_pass_number()
            else:
                # Walk-in visitors get a 6-digit numeric pass
                self.pass_number = self.generate_pass_number()
        
        # Validate pass number uniqueness ONLY among active visitors (not checked out)
        if self.pass_number and not self.check_out_time:
            existing = Visitor.objects.filter(
                pass_number=self.pass_number,
                check_out_time__isnull=True
            ).exclude(pk=self.pk)
            if existing.exists():
                from django.core.exceptions import ValidationError
                raise ValidationError(f'Pass number {self.pass_number} is currently in use by an active visitor.')
        
        super().save(*args, **kwargs)
    
    def generate_pass_number(self):
        # Generate a 6-digit pass number unique among active visitors
        while True:
            pass_number = ''.join(random.choices(string.digits, k=6))
            if not Visitor.objects.filter(pass_number=pass_number, check_out_time__isnull=True).exists():
                return pass_number

    def generate_pre_registration_pass_number(self):
        """Generate a pre-registration pass number like PR0012 unique among active visitors."""
        while True:
            num = ''.join(random.choices(string.digits, k=4))
            candidate = f"PR{num.zfill(4)}"
            if not Visitor.objects.filter(pass_number=candidate, check_out_time__isnull=True).exists():
                return candidate
    
    @property
    def is_checked_out(self):
        return self.check_out_time is not None
    
    @property
    def is_overtime(self):
        from django.utils import timezone
        import datetime
        if not self.check_out_time:
            now = timezone.now()
            midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return self.check_in_time.date() < now.date()
        return False
    
    @property
    def status(self):
        """Return visitor status: Active, Checked Out, or Upcoming"""
        if self.check_out_time:
            return 'Checked Out'
        elif self.check_in_time:
            return 'Active'
        elif self.is_pre_registered and hasattr(self, 'pre_registration'):
            if not self.pre_registration.is_verified:
                return 'Upcoming'
        
        return 'Active'

class PreRegistration(models.Model):
    visitor = models.OneToOneField(Visitor, on_delete=models.CASCADE, related_name='pre_registration')
    registered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='pre_registrations')
    unique_link = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    otp = models.CharField(max_length=6, blank=True, null=True)
    qr_code = models.ImageField(upload_to='qr_codes/', blank=True, null=True)
    is_used = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_pre_registrations')
    verified_at = models.DateTimeField(null=True, blank=True)
    expected_arrival_date = models.DateField(null=True, blank=True)
    expected_arrival_time = models.TimeField(null=True, blank=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Pre-registration for {self.visitor.full_name}"
    
    def save(self, *args, **kwargs):
        if not self.otp:
            self.otp = ''.join(random.choices(string.digits, k=6))
        super().save(*args, **kwargs)
    
    @property
    def is_expired(self):
        from django.utils import timezone
        return timezone.now() > self.expires_at
    
    @property
    def is_qr_otp_valid(self):
        """Check if QR code and OTP are valid based on arrival time window"""
        from django.utils import timezone
        from datetime import timedelta, datetime, time
        
        if not self.expected_arrival_date:
            return True  # If no arrival date set, allow usage
        
        now = timezone.now()
        
        # Convert expected_arrival_date to datetime (assume arrival at start of day if no time specified)
        if hasattr(self, 'expected_arrival_time') and self.expected_arrival_time:
            expected_arrival = timezone.make_aware(
                datetime.combine(self.expected_arrival_date, self.expected_arrival_time)
            )
        else:
            # Default to 9 AM if no specific time
            expected_arrival = timezone.make_aware(
                datetime.combine(self.expected_arrival_date, time(9, 0))
            )
        
        # Valid window: 1 hour before to 3 hours after expected arrival
        valid_start = expected_arrival - timedelta(hours=1)
        valid_end = expected_arrival + timedelta(hours=3)
        
        return valid_start <= now <= valid_end


class ALPRWhitelist(models.Model):
    """Model to store whitelisted plate numbers for ALPR camera"""
    visitor = models.ForeignKey(Visitor, on_delete=models.CASCADE, related_name='alpr_whitelists', null=True, blank=True)
    plate_number = models.CharField(max_length=20, verbose_name="License Plate Number")
    whitelisted_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(verbose_name="Whitelist Expiry")
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Camera sync status
    synced_to_camera = models.BooleanField(default=False, verbose_name="Synced to ALPR Camera")
    sync_attempts = models.PositiveIntegerField(default=0)
    last_sync_attempt = models.DateTimeField(null=True, blank=True)
    sync_error = models.TextField(blank=True, null=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['plate_number']),
            models.Index(fields=['expires_at']),
            models.Index(fields=['is_active']),
            models.Index(fields=['synced_to_camera']),
        ]
        unique_together = ['visitor', 'plate_number']
        ordering = ['-whitelisted_at']
    
    def __str__(self):
        return f"{self.plate_number} - {self.visitor.full_name if self.visitor else 'Manual Entry'}"
    
    @property
    def is_expired(self):
        from django.utils import timezone
        return timezone.now() > self.expires_at
    
    def save(self, *args, **kwargs):
        # Normalize plate number (remove spaces, convert to uppercase)
        if self.plate_number:
            self.plate_number = self.plate_number.replace(' ', '').upper()
        super().save(*args, **kwargs)


class OccurrenceLog(models.Model):
    CATEGORY_CHOICES = [
        ('routine_patrol', 'Routine Patrol'),
        ('incident', 'Incident Report'),
        ('key_management', 'Key Management'),
        ('facility', 'Facility / Maintenance'),
        ('handover', 'Shift Handover'),
        ('general', 'General Note'),
    ]

    SEVERITY_CHOICES = [
        ('normal', 'Normal / Info'),
        ('warning', 'Warning / Minor'),
        ('critical', 'Critical / Major'),
    ]

    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default='general')
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='normal')
    location = models.CharField(max_length=200, blank=True, null=True, verbose_name="Location / Area")
    title = models.CharField(max_length=200, verbose_name="Title / Summary")
    description = models.TextField(verbose_name="Detailed Description")
    attachment = models.ImageField(upload_to='occurrence_attachments/', blank=True, null=True, verbose_name="Photo Attachment")
    
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='logged_occurrences')
    officer_name = models.CharField(max_length=100, verbose_name="Officer on Duty Name")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_at']),
            models.Index(fields=['category']),
            models.Index(fields=['severity']),
            models.Index(fields=['officer_name']),
        ]

    def __str__(self):
        return f"[{self.get_category_display()}] {self.title} - {self.officer_name} ({self.created_at.strftime('%Y-%m-%d %H:%M')})"

