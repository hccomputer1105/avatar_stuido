from django.urls import path
from django.contrib.auth.views import LogoutView
from .views import CustomLoginView, role_redirect_view

urlpatterns = [
    path('login/', CustomLoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('redirect/', role_redirect_view, name='role_redirect'),
]