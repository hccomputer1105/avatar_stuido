from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from apps.users.decorators import role_required
from apps.users.models import CustomUser
from apps.studio.models import Avatar, VideoProject

@login_required
@role_required(allowed_roles=['ADMIN'])
def admin_dashboard_view(request):
    if request.method == 'POST':
        if 'create_user' in request.POST:
            username = request.POST.get('username')
            password = request.POST.get('password')
            role = request.POST.get('role')
            credits = int(request.POST.get('credits', 5))
            if not CustomUser.objects.filter(username=username).exists():
                CustomUser.objects.create_user(username=username, password=password, role=role, video_credits=credits)
                messages.success(request, f"Usuario '{username}' creado con rol {role}.")
            else:
                messages.error(request, "Ese nombre de usuario ya existe.")
            return redirect('admin_dashboard')

        elif 'add_credits' in request.POST:
            user_id = request.POST.get('user_id')
            extra_credits = int(request.POST.get('extra_credits', 5))
            target_user = get_object_or_404(CustomUser, id=user_id)
            target_user.video_credits += extra_credits
            target_user.save()
            messages.success(request, f"Se agregaron {extra_credits} créditos a {target_user.username}.")
            return redirect('admin_dashboard')

    context = {
        'users_list': CustomUser.objects.all().order_by('-date_joined'),
        'total_avatars': Avatar.objects.count(),
        'total_videos': VideoProject.objects.count(),
        'recent_videos': VideoProject.objects.all().order_by('-created_at')[:10],
    }
    return render(request, 'dashboard/index.html', context)