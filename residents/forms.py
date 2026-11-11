from django import forms
from django.utils import timezone
from .models import Resident, ResidentVehicle
from site_settings.models import AddressConfiguration


class ResidentForm(forms.ModelForm):
    # Extra non-model fields for FR provisioning
    face_image = forms.FileField(required=False)
    fr_start_time = forms.DateTimeField(required=False, widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white/50 dark:bg-gray-800/50'}))
    fr_end_time = forms.DateTimeField(required=False, widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white/50 dark:bg-gray-800/50'}))
    class Meta:
        model = Resident
        fields = ['full_name', 'phone_number', 'email', 'tower', 'level', 'unit', 'is_active']
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white/50 dark:bg-gray-800/50'}),
            'phone_number': forms.TextInput(attrs={'class': 'w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white/50 dark:bg-gray-800/50'}),
            'email': forms.EmailInput(attrs={'class': 'w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white/50 dark:bg-gray-800/50'}),
            'unit': forms.Select(attrs={'class': 'w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white/50 dark:bg-gray-800/50'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Load address configuration options
        try:
            config = AddressConfiguration.objects.first()
        except Exception:
            config = None
        # Tower
        self.fields['tower'] = forms.ChoiceField(
            required=False,
            choices=[('', 'Select Tower')] + ([(t, t) for t in (config.tower_options if config else [])] or []),
            widget=forms.Select(attrs={'class': 'w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white/50 dark:bg-gray-800/50'})
        )
        # Level
        self.fields['level'] = forms.ChoiceField(
            required=False,
            choices=[('', 'Select Level')] + ([(l, l) for l in (config.level_options if config else [])] or []),
            widget=forms.Select(attrs={'class': 'w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white/50 dark:bg-gray-800/50'})
        )
        # Unit
        self.fields['unit'] = forms.ChoiceField(
            required=False,
            choices=[('', 'Select Unit')] + ([(u, u) for u in (config.unit_options if config else [])] or []),
            widget=forms.Select(attrs={'class': 'w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white/50 dark:bg-gray-800/50'})
        )

        # Initialize FR validity to now and +1 year by default (adjustable)
        try:
            now = timezone.localtime(timezone.now())
            start_val = None
            end_val = None
            if getattr(self.instance, 'fr_valid_from', None):
                start_val = timezone.localtime(self.instance.fr_valid_from)
            if getattr(self.instance, 'fr_valid_until', None):
                end_val = timezone.localtime(self.instance.fr_valid_until)
            self.fields['fr_start_time'].initial = (start_val or now).strftime('%Y-%m-%dT%H:%M')
            self.fields['fr_end_time'].initial = (end_val or (now + timezone.timedelta(days=365))).strftime('%Y-%m-%dT%H:%M')
        except Exception:
            pass


class ResidentVehicleForm(forms.ModelForm):
    class Meta:
        model = ResidentVehicle
        fields = ['plate_number', 'start_time', 'end_time', 'is_active']
        widgets = {
            'plate_number': forms.TextInput(attrs={'class': 'w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white/50 dark:bg-gray-800/50'}),
            'start_time': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white/50 dark:bg-gray-800/50'}),
            'end_time': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white/50 dark:bg-gray-800/50'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded'}),
        }

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_time')
        end = cleaned.get('end_time')
        if end and start and end <= start:
            raise forms.ValidationError('End time harus lebih besar dari Start time.')
        return cleaned