"""
URL configuration for customer_intelligence project.
"""
from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse

from rest_framework import routers
from customers.views import CustomerViewSet


def health_check(request):
    """Health check endpoint para Docker/Load Balancer"""
    return JsonResponse({'status': 'healthy', 'service': 'customer-intelligence'})


# API Router
router = routers.DefaultRouter()
router.register(r'customers', CustomerViewSet)

urlpatterns = [
    path('health/', health_check, name='health_check'),
    path('admin/', admin.site.urls),
    path('tenants/', include('tenants.urls')),
    path('importer/', include('importer.urls')),
    path('api/', include(router.urls)),
]

# Servir arquivos de media em desenvolvimento
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
