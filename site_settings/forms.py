from django import forms
from .models import Site, SiteLogo

class SiteForm(forms.ModelForm):
    class Meta:
        model = Site
        fields = ['name', 'address', 'contact_number', 'email']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white/50 dark:bg-gray-800/50 focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                'placeholder': 'Enter site name'
            }),
            'address': forms.Textarea(attrs={
                'class': 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white/50 dark:bg-gray-800/50 focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                'placeholder': 'Enter site address',
                'rows': 3
            }),
            'contact_number': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white/50 dark:bg-gray-800/50 focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                'placeholder': 'Enter contact number'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white/50 dark:bg-gray-800/50 focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                'placeholder': 'Enter email address'
            }),
        }
        labels = {
            'name': 'Site Name',
            'address': 'Address',
            'contact_number': 'Contact Number',
            'email': 'Email',
        }

class SiteLogoForm(forms.ModelForm):
    class Meta:
        model = SiteLogo
        fields = ['logo_light', 'logo_dark', 'alt_text']
        widgets = {
            'logo_light': forms.FileInput(attrs={
                'class': 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white/50 dark:bg-gray-800/50 focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                'accept': 'image/*'
            }),
            'logo_dark': forms.FileInput(attrs={
                'class': 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white/50 dark:bg-gray-800/50 focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                'accept': 'image/*'
            }),
            'alt_text': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white/50 dark:bg-gray-800/50 focus:ring-2 focus:ring-blue-500 focus:border-transparent',
                'placeholder': 'Enter alt text for logo'
            }),
        }
        labels = {
            'logo_light': 'Logo for Light Theme',
            'logo_dark': 'Logo for Dark Theme',
            'alt_text': 'Alt Text',
        }