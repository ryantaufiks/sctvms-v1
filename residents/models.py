from django.conf import settings
from django.db import models
from django.utils import timezone


class Resident(models.Model):
    full_name = models.CharField(max_length=120)
    phone_number = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    # Address fields aligned with Dashboard (Tower, Level, Unit)
    tower = models.CharField(max_length=10, blank=True)
    level = models.CharField(max_length=10, blank=True)
    unit = models.CharField(
        max_length=50, blank=True, help_text="Unit/Apartment/House number"
    )
    is_active = models.BooleanField(default=True)
    # Face Reader (FR) provisioning fields
    terminal_user_id = models.CharField(max_length=32, blank=True)
    fr_valid_from = models.DateTimeField(null=True, blank=True)
    fr_valid_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['phone_number']),
            models.Index(fields=['email']),
            models.Index(fields=['is_active']),
            models.Index(fields=['tower', 'level', 'unit']),
        ]

    def __str__(self):
        label = self.full_name
        parts = [p for p in [self.tower, self.level, self.unit] if p]
        if parts:
            label += f" (" + "/".join(parts) + ")"
        return label

    @property
    def vehicles_count(self):
        return self.vehicles.filter(is_active=True).count()

    def get_next_plate_order(self):
        """
        Get the next available plate_order for this resident.
        Returns the smallest unused plate_order (1-4), or None if all 4 slots are used.
        """
        used_orders = set(
            self.vehicles.exclude(plate_order__isnull=True)
            .values_list('plate_order', flat=True)
        )
        for order in [1, 2, 3, 4]:
            if order not in used_orders:
                return order
        return None

    def get_next_plate_orders(self, count):
        """
        Get the next N available plate_orders for this resident.
        Returns a list of available plate_orders (up to count items).
        If not enough slots available, returns fewer items.
        """
        used_orders = set(
            self.vehicles.exclude(plate_order__isnull=True)
            .values_list('plate_order', flat=True)
        )
        available = []
        for order in [1, 2, 3, 4]:
            if order not in used_orders and len(available) < count:
                available.append(order)
        return available


class ResidentVehicle(models.Model):
    resident = models.ForeignKey(
        Resident, on_delete=models.CASCADE, related_name="vehicles"
    )
    plate_number = models.CharField(max_length=20)
    plate_order = models.PositiveSmallIntegerField(
        null=True, blank=True, choices=[(1, "1"), (2, "2"), (3, "3"), (4, "4")]
    )
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    remarks = models.CharField(max_length=255, blank=True)
    whitelist_synced = models.BooleanField(default=False, help_text="Indicates if vehicle is synced to ALPR camera whitelist")
    whitelist_synced_at = models.DateTimeField(null=True, blank=True, help_text="Last successful sync timestamp")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["plate_number"]),
            models.Index(fields=["plate_order"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["end_time"]),
        ]
        unique_together = ("resident", "plate_number")

    def __str__(self):
        return f"{self.plate_number} - {self.resident.full_name}"

    @property
    def expiry_hours(self):
        if self.end_time and self.start_time:
            seconds = (self.end_time - self.start_time).total_seconds()
            return max(1, int(seconds // 3600))
        return 24


class ResidentVehicleLog(models.Model):
    """
    Log of resident vehicle detections from ALPR camera.
    Records when a resident's vehicle is detected entering/exiting.
    """
    DIRECTION_CHOICES = [
        ('in', 'In'),
        ('out', 'Out'),
    ]
    
    resident = models.ForeignKey(
        Resident, on_delete=models.CASCADE, related_name="vehicle_logs"
    )
    vehicle = models.ForeignKey(
        ResidentVehicle, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="logs"
    )
    plate_number = models.CharField(max_length=20)
    direction = models.CharField(max_length=3, choices=DIRECTION_CHOICES, default='in')
    detected_at = models.DateTimeField(default=timezone.now)
    snapshot_path = models.CharField(max_length=500, blank=True)
    
    class Meta:
        ordering = ['-detected_at']
        indexes = [
            models.Index(fields=['-detected_at']),
            models.Index(fields=['plate_number']),
            models.Index(fields=['direction']),
        ]
    
    def __str__(self):
        return f"{self.plate_number} - {self.resident.full_name} ({self.direction}) @ {self.detected_at}"
    
    @property
    def resident_unit(self):
        """Returns formatted unit info (Tower/Level/Unit)"""
        parts = [p for p in [self.resident.tower, self.resident.level, self.resident.unit] if p]
        return "/".join(parts) if parts else "-"
