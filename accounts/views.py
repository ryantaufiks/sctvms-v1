from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User, Group
from django.contrib import messages
from django.http import HttpResponseForbidden
from .models import UserProfile, ActivityLog
from site_settings.models import Site

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard:index')
        
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            ActivityLog.log(
                user=user,
                action='login',
                module='auth',
                description=f'User {user.username} logged in',
                request=request
            )
            next_url = request.GET.get('next', 'dashboard:index')
            return redirect(next_url)
        else:
            ActivityLog.log(
                user=None,
                action='login',
                module='auth',
                description=f'Failed login attempt for username: {username}',
                request=request
            )
            messages.error(request, 'Invalid username or password')
    
    # Get the first site logo for login page
    from site_settings.models import SiteLogo
    site_logo = SiteLogo.objects.first()
    
    context = {
        'site_logo': site_logo
    }
    
    return render(request, 'accounts/login.html', context)

def logout_view(request):
    if request.user.is_authenticated:
        ActivityLog.log(
            user=request.user,
            action='logout',
            module='auth',
            description=f'User {request.user.username} logged out',
            request=request
        )
    logout(request)
    return redirect('login')

@login_required
def dashboard(request):
    return redirect('dashboard:index')

@login_required
def profile(request):
    return render(request, 'accounts/profile.html')

def quick_guide_view(request):
    return render(request, 'quick_guide.html')

