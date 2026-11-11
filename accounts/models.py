from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

class UserProfile(models.Model):
    ROLE_CHOICES = (
        ('admin', 'Admin'),
        ('management', 'Management'),
        ('staff', 'Staff'),
        ('security_officer', 'Security Officer'),
    )
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()}"
    
    def _normalized_role(self):
        """Normalize role for case-insensitive comparison"""
        if self.role:
            return str(self.role).strip().lower().replace(' ', '_')
        return ''
    
    @property
    def is_admin(self):
        return self._normalized_role() == 'admin'
    
    @property
    def is_management(self):
        return self._normalized_role() == 'management'
    
    @property
    def is_staff(self):
        return self._normalized_role() == 'staff'
    
    @property
    def is_security_officer(self):
        return self._normalized_role() in ('security_officer', 'officer', 'security')

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(
            user=instance,
            defaults={'role': 'admin'}
        )

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if hasattr(instance, 'profile'):
        instance.profile.save()


class ActivityLog(models.Model):
    """
    Model to track all user activities in the system.
    """
    ACTION_CHOICES = (
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('create', 'Create'),
        ('update', 'Update'),
        ('delete', 'Delete'),
        ('view', 'View'),
        ('export', 'Export'),
        ('check_in', 'Check In'),
        ('check_out', 'Check Out'),
        ('provision', 'Provision'),
        ('sync', 'Sync'),
        ('other', 'Other'),
    )
    
    MODULE_CHOICES = (
        ('visitor', 'Visitor'),
        ('resident', 'Resident'),
        ('vehicle', 'Vehicle'),
        ('user', 'User'),
        ('settings', 'Settings'),
        ('report', 'Report'),
        ('dashboard', 'Dashboard'),
        ('auth', 'Authentication'),
        ('alpr', 'ALPR Camera'),
        ('fr_terminal', 'FR Terminal'),
        ('other', 'Other'),
    )
    
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='activity_logs')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    module = models.CharField(max_length=20, choices=MODULE_CHOICES)
    description = models.TextField()
    target_id = models.IntegerField(null=True, blank=True)
    target_type = models.CharField(max_length=100, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    extra_data = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['action', 'created_at']),
            models.Index(fields=['module', 'created_at']),
        ]
    
    def __str__(self):
        username = self.user.username if self.user else 'System'
        return f"{username} - {self.get_action_display()} - {self.get_module_display()} - {self.created_at}"
    
    @classmethod
    def log(cls, user, action, module, description, target_id=None, target_type='', request=None, extra_data=None):
        """
        Helper method to create activity log entries.
        """
        ip_address = None
        user_agent = ''
        
        if request:
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip_address = x_forwarded_for.split(',')[0].strip()
            else:
                ip_address = request.META.get('REMOTE_ADDR')
            user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]
        
        return cls.objects.create(
            user=user if user and user.is_authenticated else None,
            action=action,
            module=module,
            description=description,
            target_id=target_id,
            target_type=target_type,
            ip_address=ip_address,
            user_agent=user_agent,
            extra_data=extra_data
        )
