from django.urls import path
from .views import studio_home_view, studio_gallery_view

urlpatterns = [
    path('', studio_home_view, name='studio_home'),
    path('gallery/', studio_gallery_view, name='studio_gallery'),
]