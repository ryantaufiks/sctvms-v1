"""
URL configuration for vms project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.conf.urls.i18n import i18n_patterns
from accounts.views import login_view, logout_view, quick_guide_view

urlpatterns = [
    path('i18n/', include('django.conf.urls.i18n')),
]

urlpatterns += i18n_patterns(
    path('superadmin/', admin.site.urls),
    path('accounts/', include('accounts.urls', namespace='accounts')),
    path('dashboard/', include('dashboard.urls', namespace='dashboard')),
    path('visitors/', include('visitors.urls', namespace='visitors')),
    path('settings/', include('site_settings.urls', namespace='site_settings')),
    path('residents/', include('residents.urls', namespace='residents')),
    path('users/', include('user_management.urls', namespace='user_management')),
    path('reports/', include('reports.urls', namespace='reports')),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('quick-guide/', quick_guide_view, name='quick_guide'),
    path('', login_view, name='home'),
    prefix_default_language=False,
)

# API endpoints (outside i18n patterns)
urlpatterns += [
    path('api/', include('dashboard.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
