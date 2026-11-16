from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView

urlpatterns = [
    path('django-admin/', admin.site.urls),
    path('', RedirectView.as_view(pattern_name='login', permanent=False)),
    path('auth/', include('apps.users.urls')),
    path('admin-panel/', include('apps.dashboard.urls')),
    path('studio/', include('apps.studio.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)