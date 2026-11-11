from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from functools import wraps
from django.contrib import messages
import logging

logger = logging.getLogger(__name__)

def role_required(allowed_roles):
    """Decorator that allows multiple roles"""
    if isinstance(allowed_roles, str):
        allowed_roles = [allowed_roles]
    
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            try:
                if request.user.profile.role in allowed_roles:
                    return view_func(request, *args, **kwargs)
                else:
                    messages.error(request, "You don't have permission to access this page")
                    return redirect('dashboard:index')
            except:
                messages.error(request, "You don't have permission to access this page")
                return redirect('dashboard:index')
        return _wrapped_view
    return decorator

# Specific role decorators
def admin_required(view_func):
    """Admin: Can manage all"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        try:
            if request.user.profile.is_admin:
                return view_func(request, *args, **kwargs)
            else:
                messages.error(request, "Admin access required")
                return redirect('dashboard:index')
        except:
            messages.error(request, "Admin access required")
            return redirect('dashboard:index')
    return _wrapped_view

def management_or_admin_required(view_func):
    """Management or Admin access"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        try:
            if request.user.profile.role in ['admin', 'management']:
                return view_func(request, *args, **kwargs)
            else:
                messages.error(request, "Management or Admin access required")
                return redirect('dashboard:index')
        except:
            messages.error(request, "Management or Admin access required")
            return redirect('dashboard:index')
    return _wrapped_view

def staff_or_above_required(view_func):
    """Staff, Management, or Admin access (robust)"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        try:
            user = request.user
            profile = getattr(user, 'profile', None)

            # Normalize role safely if present
            role_value = None
            if profile and getattr(profile, 'role', None):
                role_value = str(profile.role).strip().lower().replace(' ', '_')

            allowed = False

            # Allow superusers explicitly
            if getattr(user, 'is_superuser', False):
                allowed = True

            # Allow via explicit profile boolean helpers
            if profile and (getattr(profile, 'is_admin', False)
                            or getattr(profile, 'is_management', False)
                            or getattr(profile, 'is_staff', False)):
                allowed = True

            # Fallback: allow via normalized role string
            if role_value in {'admin', 'management', 'staff'}:
                allowed = True

            # DEBUG LOGGING
            logger.debug(
                "staff_or_above_required user=%s superuser=%s role=%s allowed=%s",
                getattr(user, 'username', None),
                getattr(user, 'is_superuser', None),
                role_value,
                allowed,
            )

            if allowed:
                return view_func(request, *args, **kwargs)

            messages.error(request, "Staff access or above required")
            return redirect('dashboard:index')
        except Exception as e:
            logger.warning(
                "staff_or_above_required exception user=%s error=%s",
                getattr(request.user, 'username', None),
                e,
                exc_info=True,
            )
            messages.error(request, "Staff access or above required")
            return redirect('dashboard:index')
    return _wrapped_view

def security_officer_required(view_func):
    """Security Officer access"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        try:
            if request.user.profile.is_security_officer:
                return view_func(request, *args, **kwargs)
            else:
                messages.error(request, "Security Officer access required")
                return redirect('dashboard:index')
        except:
            messages.error(request, "Security Officer access required")
            return redirect('dashboard:index')
    return _wrapped_view

def can_manage_users(view_func):
    """Admin and Management can manage users"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        try:
            user_role = request.user.profile.role
            if user_role in ['admin', 'management']:
                return view_func(request, *args, **kwargs)
            else:
                messages.error(request, "You don't have permission to manage users")
                return redirect('dashboard:index')
        except:
            messages.error(request, "You don't have permission to manage users")
            return redirect('dashboard:index')
    return _wrapped_view


def can_view_reports(view_func):
    """Admin, Management, Staff, and Security Officer can view reports"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        try:
            user = request.user
            profile = getattr(user, 'profile', None)

            # Normalize role safely if present
            role_value = None
            if profile and getattr(profile, 'role', None):
                role_value = str(profile.role).strip().lower().replace(' ', '_')

            allowed = False

            # Allow superusers explicitly
            if getattr(user, 'is_superuser', False):
                allowed = True

            # Allow via explicit profile boolean helpers
            if profile and (getattr(profile, 'is_admin', False)
                            or getattr(profile, 'is_management', False)
                            or getattr(profile, 'is_security_officer', False)
                            or getattr(profile, 'is_staff', False)):
                allowed = True

            # Fallback: allow via normalized role string
            if role_value in {'admin', 'management', 'security_officer', 'staff'}:
                allowed = True

            # DEBUG LOGGING START
            logger.debug(
                "can_view_reports user=%s superuser=%s role=%s allowed=%s",
                getattr(user, 'username', None),
                getattr(user, 'is_superuser', None),
                role_value,
                allowed,
            )
            # DEBUG LOGGING END

            if allowed:
                return view_func(request, *args, **kwargs)

            messages.error(request, "You don't have permission to view reports")
            return redirect('dashboard:index')
        except Exception as e:
            # DEBUG LOGGING START
            logger.warning(
                "can_view_reports exception user=%s error=%s",
                getattr(request.user, 'username', None),
                e,
                exc_info=True,
            )
            # DEBUG LOGGING END
            messages.error(request, "You don't have permission to view reports")
            return redirect('dashboard:index')
    return _wrapped_view