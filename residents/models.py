from django.db import models
from django.conf import settings
from django.utils import timezone


class Resident(models.Model):
    full_name = models.CharField(max_length=120)
    phone_number = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    # Address fields aligned with Dashboard (Tower, Level, Unit)
    tower = models.CharField(max_length=10, blank=True)
    level = models.CharField(max_length=10, blank=True)
    unit = models.CharField(max_length=50, blank=True, help_text='Unit/Apartment/House number')
    is_active = models.BooleanField(default=True)
    # Face Reader (FR) provisioning fields
    terminal_user_id = models.CharField(max_length=32, blank=True)
    fr_valid_from = models.DateTimeField(null=True, blank=True)
    fr_valid_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        label = self.full_name
        parts = [p for p in [self.tower, self.level, self.unit] if p]
        if parts:
            label += f" (" + "/".join(parts) + ")"
        return label

    @property
    def vehicles_count(self):
        return self.vehicles.filter(is_active=True).count()


class ResidentVehicle(models.Model):
    resident = models.ForeignKey(Resident, on_delete=models.CASCADE, related_name='vehicles')
    plate_number = models.CharField(max_length=20)
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['plate_number']),
            models.Index(fields=['is_active']),
            models.Index(fields=['end_time']),
        ]
        unique_together = ('resident', 'plate_number')

    def __str__(self):
        return f"{self.plate_number} - {self.resident.full_name}"

    @property
    def expiry_hours(self):
        if self.end_time and self.start_time:
            seconds = (self.end_time - self.start_time).total_seconds()
            return max(1, int(seconds // 3600))
        return 24