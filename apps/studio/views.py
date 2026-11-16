from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from apps.users.decorators import role_required
from .models import Avatar, VideoProject
from .forms import AvatarForm, VideoProjectForm
from .services import start_video_job_async


@login_required
@role_required(allowed_roles=['ADMIN', 'CREATOR'])
def studio_home_view(request):
    avatars = Avatar.objects.filter(user=request.user).order_by('-created_at')
    videos = VideoProject.objects.filter(user=request.user).order_by('-created_at')
    
    avatar_form = AvatarForm()
    video_form = VideoProjectForm(user=request.user)

    if request.method == 'POST':
        if 'create_avatar' in request.POST:
            avatar_form = AvatarForm(request.POST, request.FILES)
            if avatar_form.is_valid():
                avatar = avatar_form.save(commit=False)
                avatar.user = request.user
                avatar.save()
                messages.success(request, f"Avatar '{avatar.name}' creado correctamente.")
                return redirect('studio_home')

        elif 'create_video' in request.POST:
            # Aquí es donde va la línea actualizada con request.FILES:
            video_form = VideoProjectForm(request.user, request.POST, request.FILES)
            if video_form.is_valid():
                if request.user.video_credits > 0 or request.user.is_admin_role():
                    video = video_form.save(commit=False)
                    video.user = request.user
                    video.status = VideoProject.Status.PENDING
                    video.save()

                    if not request.user.is_admin_role():
                        request.user.video_credits -= 1
                        request.user.save()

                    start_video_job_async(video.id)

                    messages.success(request, "Video en proceso de generación. Recarga en unos segundos para verlo.")
                    return redirect('studio_home')
                else:
                    messages.error(request, "No tienes créditos suficientes. Solicita recarga al administrador.")

    context = {
        'avatars': avatars,
        'videos': videos,
        'avatar_form': avatar_form,
        'video_form': video_form,
    }
    return render(request, 'studio/home.html', context)


@login_required
def studio_gallery_view(request):
    videos = VideoProject.objects.filter(status=VideoProject.Status.COMPLETED).order_by('-created_at')
    return render(request, 'studio/gallery.html', {'videos': videos})


