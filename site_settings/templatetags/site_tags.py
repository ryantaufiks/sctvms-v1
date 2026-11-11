from django import template
from site_settings.models import Site, SiteLogo

register = template.Library()

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