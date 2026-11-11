from django.contrib import admin
from .models import Resident, ResidentVehicle


@admin.register(Resident)
class ResidentAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'unit', 'phone_number', 'email', 'is_active', 'vehicles_count', 'created_at')
    search_fields = ('full_name', 'unit', 'phone_number', 'email')
    list_filter = ('is_active',)
    readonly_fields = ('terminal_user_id', 'fr_valid_from', 'fr_valid_until')


@admin.register(ResidentVehicle)
class ResidentVehicleAdmin(admin.ModelAdmin):
    list_display = ('plate_number', 'resident', 'is_active', 'start_time', 'end_time', 'created_by')
    list_filter = ('is_active',)
    search_fields = ('plate_number', 'resident__full_name', 'resident__unit')