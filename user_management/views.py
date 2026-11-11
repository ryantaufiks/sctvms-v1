from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.db import transaction
from django.http import JsonResponse
from accounts.models import UserProfile
from accounts.decorators import admin_required, can_manage_users, management_or_admin_required

@login_required
@can_manage_users
def user_list(request):
    """List all users for admin"""
    search_query = request.GET.get('search', '')
    role_filter = request.GET.get('role', '')
    
    users = User.objects.select_related('profile').all()
    
    if search_query:
        users = users.filter(
            Q(username__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(email__icontains=search_query)
        )
    
    if role_filter:
        users = users.filter(profile__role=role_filter)
    
    paginator = Paginator(users, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'role_filter': role_filter,
        'role_choices': UserProfile.ROLE_CHOICES,
    }
    
    return render(request, 'user_management/user_list.html', context)

@login_required
@can_manage_users
def create_user(request):
    """Create new user - Admin can create all roles, Management can create Staff"""
    user_profile = request.user.profile
    
    # Check permissions
    if user_profile.role == 'admin':
        allowed_roles = ['admin', 'management', 'staff', 'security_officer']
    elif user_profile.role == 'management':
        allowed_roles = ['staff']
    else:
        messages.error(request, 'You do not have permission to create users.')
        return redirect('dashboard:index')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        role = request.POST.get('role')
        phone_number = request.POST.get('phone_number')
        
        # Validation
        if password != confirm_password:
            messages.error(request, 'Passwords do not match.')
        elif role not in allowed_roles:
            messages.error(request, 'Invalid role selected.')
        elif User.objects.filter(username=username).exists():
            messages.error(request, 'Username already exists.')
        elif User.objects.filter(email=email).exists():
            messages.error(request, 'Email already exists.')
        else:
            try:
                # Create user and safely attach/update profile created by signal
                with transaction.atomic():
                    user = User.objects.create_user(
                        username=username,
                        email=email,
                        password=password,
                        first_name=first_name,
                        last_name=last_name
                    )

                    # Use get_or_create to avoid UNIQUE constraint violation from OneToOne relation
                    profile, _ = UserProfile.objects.get_or_create(user=user)
                    profile.role = role
                    profile.phone_number = phone_number
                    profile.save()
                
                messages.success(request, f'User {username} created successfully.')
                return redirect('user_management:user_list')
                
            except Exception as e:
                messages.error(request, f'Error creating user: {str(e)}')
    
    context = {
        'allowed_roles': allowed_roles,
        'role_choices': [(role, role.replace('_', ' ').title()) for role in allowed_roles],
    }
    
    return render(request, 'user_management/create_user.html', context)

@login_required
@can_manage_users
def edit_user(request, user_id):
    """Edit existing user"""
    user_profile = request.user.profile
    target_user = get_object_or_404(User, id=user_id)
    
    # Check permissions
    if user_profile.role == 'admin':
        # Admin can edit all users
        allowed_roles = ['admin', 'management', 'staff', 'security_officer']
    elif user_profile.role == 'management':
        # Management can only edit staff users
        if target_user.profile.role != 'staff':
            messages.error(request, 'You can only edit staff users.')
            return redirect('dashboard:index')
        allowed_roles = ['staff']
    else:
        messages.error(request, 'You do not have permission to edit users.')
        return redirect('dashboard:index')
    
    if request.method == 'POST':
        email = request.POST.get('email')
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        role = request.POST.get('role')
        phone_number = request.POST.get('phone_number')
        is_active = request.POST.get('is_active') == 'on'
        is_staff = request.POST.get('is_staff') == 'on'
        new_password1 = request.POST.get('new_password1', '').strip()
        new_password2 = request.POST.get('new_password2', '').strip()
        
        # Self-protection: prevent admin from demoting themselves
        is_self_edit = (request.user.id == target_user.id)
        if is_self_edit and role != 'admin':
            messages.error(request, 'You cannot change your own admin role.')
            return render(request, 'user_management/edit_user.html', {
                'target_user': target_user,
                'allowed_roles': allowed_roles,
                'role_choices': [(r, r.replace('_', ' ').title()) for r in allowed_roles],
            })
        
        # Self-protection: prevent admin from disabling their own account
        if is_self_edit and not is_active:
            messages.error(request, 'You cannot deactivate your own account.')
            return render(request, 'user_management/edit_user.html', {
                'target_user': target_user,
                'allowed_roles': allowed_roles,
                'role_choices': [(r, r.replace('_', ' ').title()) for r in allowed_roles],
            })
        
        # Last-admin protection: prevent demoting the last admin
        if target_user.profile.role == 'admin' and role != 'admin':
            admin_count = User.objects.filter(profile__role='admin', is_active=True).count()
            if admin_count <= 1:
                messages.error(request, 'Cannot demote the last admin user. Create another admin first.')
                return render(request, 'user_management/edit_user.html', {
                    'target_user': target_user,
                    'allowed_roles': allowed_roles,
                    'role_choices': [(r, r.replace('_', ' ').title()) for r in allowed_roles],
                })
        
        # Password validation
        if new_password1 or new_password2:
            if new_password1 != new_password2:
                messages.error(request, 'Passwords do not match.')
                return render(request, 'user_management/edit_user.html', {
                    'target_user': target_user,
                    'allowed_roles': allowed_roles,
                    'role_choices': [(role, role.replace('_', ' ').title()) for role in allowed_roles],
                })
            if len(new_password1) < 6:
                messages.error(request, 'Password must be at least 6 characters long.')
                return render(request, 'user_management/edit_user.html', {
                    'target_user': target_user,
                    'allowed_roles': allowed_roles,
                    'role_choices': [(role, role.replace('_', ' ').title()) for role in allowed_roles],
                })
        
        # Validation
        if role not in allowed_roles:
            messages.error(request, 'Invalid role selected.')
        elif User.objects.filter(email=email).exclude(id=target_user.id).exists():
            messages.error(request, 'Email already exists.')
        else:
            try:
                # Update user
                target_user.email = email
                target_user.first_name = first_name
                target_user.last_name = last_name
                target_user.is_active = is_active
                target_user.is_staff = is_staff
                target_user.save()
                
                # Update password if provided
                if new_password1:
                    target_user.set_password(new_password1)
                    target_user.save()
                
                # Update user profile
                target_user.profile.role = role
                target_user.profile.phone_number = phone_number
                target_user.profile.save()
                
                messages.success(request, f'User {target_user.username} updated successfully.' + (' Password has been changed.' if new_password1 else ''))
                return redirect('user_management:user_list')
                
            except Exception as e:
                messages.error(request, f'Error updating user: {str(e)}')
    
    context = {
        'target_user': target_user,
        'allowed_roles': allowed_roles,
        'role_choices': [(role, role.replace('_', ' ').title()) for role in allowed_roles],
    }
    
    return render(request, 'user_management/edit_user.html', context)

@login_required
@can_manage_users
def delete_user(request, user_id):
    """Delete a user - Admin only, cannot delete self or last admin"""
    if request.method != 'POST':
        return redirect('user_management:user_list')
    
    target_user = get_object_or_404(User, id=user_id)
    
    # Cannot delete yourself
    if request.user.id == target_user.id:
        messages.error(request, 'You cannot delete your own account.')
        return redirect('user_management:user_list')
    
    # Cannot delete the last admin
    if target_user.profile.role == 'admin':
        admin_count = User.objects.filter(profile__role='admin', is_active=True).count()
        if admin_count <= 1:
            messages.error(request, 'Cannot delete the last admin user. Create another admin first.')
            return redirect('user_management:user_list')
    
    # Management can only delete staff
    if request.user.profile.role == 'management' and target_user.profile.role != 'staff':
        messages.error(request, 'You can only delete staff users.')
        return redirect('user_management:user_list')
    
    username = target_user.username
    target_user.delete()
    messages.success(request, f'User {username} has been deleted.')
    return redirect('user_management:user_list')
