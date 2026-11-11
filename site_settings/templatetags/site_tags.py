from django import template
from site_settings.models import Site, SiteLogo, SiteConfiguration

register = template.Library()

@register.simple_tag
def get_site_config():
    """Get the site configuration for CSS mode and other settings"""
    try:
        config = SiteConfiguration.objects.first()
        if config:
            return config
        return type('obj', (object,), {'use_local_css': False})()
    except:
        return type('obj', (object,), {'use_local_css': False})()

@register.simple_tag
def get_site_logo():
    """Get the site logo for the current site"""
    try:
        site = Site.objects.first()
        if site:
            try:
                return site.logo
            except SiteLogo.DoesNotExist:
                return None
        return None
    except:
        return None

@register.simple_tag
def get_site():
    """Get the current site"""
    try:
        return Site.objects.first()
    except:
        return None