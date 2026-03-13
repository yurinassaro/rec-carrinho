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
from customers.webhooks import woo_order_created, woo_order_updated
from customers.webhooks_meta import meta_webhook
from customers.api_chrome_extension import chrome_extension_lead, chrome_extension_check
from comunicacao.api import receber_evento

# Configurar nome do Admin
admin.site.site_header = 'Carrinho e Leads'
admin.site.site_title = 'Carrinho e Leads'
admin.site.index_title = 'Painel de Administracao'


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
    # Bling OAuth
    path('bling/', include('bling.urls')),
    # Webhooks WooCommerce
    path('webhooks/woo/<slug:empresa_slug>/order-created/', woo_order_created, name='woo_order_created'),
    path('webhooks/woo/<slug:empresa_slug>/order-created', woo_order_created),
    path('webhooks/woo/<slug:empresa_slug>/order-updated/', woo_order_updated, name='woo_order_updated'),
    path('webhooks/woo/<slug:empresa_slug>/order-updated', woo_order_updated),
    # Webhook Meta WhatsApp (recebe respostas e status updates)
    path('webhooks/meta/', meta_webhook, name='meta_webhook'),
    # API Chrome Extension - WhatsApp Web
    path('api/v1/leads/chrome-extension/<slug:empresa_slug>/', chrome_extension_lead, name='chrome_ext_lead'),
    path('api/v1/leads/chrome-extension/<slug:empresa_slug>/check/', chrome_extension_check, name='chrome_ext_check'),
    # API genérica de eventos (multi-plataforma)
    path('api/v1/events/', receber_evento, name='api_events'),
]

# Servir arquivos de media em desenvolvimento
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
