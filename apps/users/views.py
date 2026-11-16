from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import views as auth_views

class CustomLoginView(auth_views.LoginView):
    template_name = 'users/login.html'
    redirect_authenticated_user = True

@login_required
def role_redirect_view(request):
    """Redirige al usuario según su rol al iniciar sesión."""
    user = request.user
    if user.is_admin_role():
        return redirect('admin_dashboard') # Va al Administrativo
    elif user.is_creator_role():
        return redirect('studio_home')     # Va al Aplicativo de Avatares
    else:
        return redirect('studio_gallery')  # Va a galería de solo lectura
