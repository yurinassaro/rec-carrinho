"""
URL configuration for customer_intelligence project.
"""
from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse, HttpResponse
from django.views.generic import TemplateView

from rest_framework import routers
from customers.views import CustomerViewSet
from customers.webhooks import woo_order_created, woo_order_updated
from customers.webhooks_meta import meta_webhook
from customers.views_meta_deletion import meta_data_deletion, meta_data_deletion_status
from customers.api_chrome_extension import chrome_extension_lead, chrome_extension_check, chrome_extension_pipelines
from customers.api_triagem import (chrome_extension_triagem, chrome_extension_crm_triagem,
                                   chrome_extension_sugerir)
from comunicacao.api import receber_evento
from customers.api_lead_atacado import receber_lead_atacado
from customers.api_webhook_form import webhook_form_lead, webhook_form_pipelines, webhook_form_docs

# Configurar nome do Admin
admin.site.site_header = 'Carrinho e Leads'
admin.site.site_title = 'Carrinho e Leads'
admin.site.index_title = 'Painel de Administracao'


def health_check(request):
    """Health check endpoint para Docker/Load Balancer"""
    return JsonResponse({'status': 'healthy', 'service': 'customer-intelligence'})


def robots_txt(request):
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        "User-agent: facebookexternalhit\n"
        "Allow: /\n"
        "\n"
        "User-agent: Facebot\n"
        "Allow: /\n"
        "\n"
        "User-agent: meta-externalagent\n"
        "Allow: /\n"
        "\n"
        "Disallow: /admin/\n"
        "Disallow: /api/\n"
        "Disallow: /webhooks/\n"
        "Disallow: /crm/\n"
    )
    return HttpResponse(content, content_type='text/plain')


# API Router
router = routers.DefaultRouter()
router.register(r'customers', CustomerViewSet)

urlpatterns = [
    path('', TemplateView.as_view(template_name='home.html'), name='home'),
    path('robots.txt', robots_txt, name='robots_txt'),
    path('health/', health_check, name='health_check'),
    path('privacidade/', TemplateView.as_view(template_name='legal/privacidade.html'), name='privacidade'),
    path('termos/', TemplateView.as_view(template_name='legal/termos.html'), name='termos'),
    path('exclusao-dados/', TemplateView.as_view(template_name='legal/exclusao_dados.html'), name='exclusao_dados'),
    path('lgpd/', TemplateView.as_view(template_name='legal/exclusao_dados.html'), name='lgpd'),
    path('admin/', admin.site.urls),
    path('crm/', include('customers.urls_crm')),
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
    # Meta Data Deletion Callback (POST com signed_request)
    path('meta/data-deletion/', meta_data_deletion, name='meta_data_deletion'),
    path('meta/data-deletion-status/', meta_data_deletion_status, name='meta_data_deletion_status'),
    # API Chrome Extension - WhatsApp Web
    path('api/v1/leads/chrome-extension/<slug:empresa_slug>/', chrome_extension_lead, name='chrome_ext_lead'),
    path('api/v1/leads/chrome-extension/<slug:empresa_slug>/check/', chrome_extension_check, name='chrome_ext_check'),
    path('api/v1/leads/chrome-extension/<slug:empresa_slug>/pipelines/', chrome_extension_pipelines, name='chrome_ext_pipelines'),
    path('api/v1/leads/chrome-extension/<slug:empresa_slug>/triagem/', chrome_extension_triagem, name='chrome_ext_triagem'),
    path('api/v1/leads/chrome-extension/<slug:empresa_slug>/crm-triagem/', chrome_extension_crm_triagem, name='chrome_ext_crm_triagem'),
    path('api/v1/leads/chrome-extension/<slug:empresa_slug>/sugerir/', chrome_extension_sugerir, name='chrome_ext_sugerir'),
    # API Leads Atacado
    path('api/v1/leads/atacado/<slug:empresa_slug>/', receber_lead_atacado, name='api_lead_atacado'),
    # API Webhook Formulários Externos
    path('api/v1/webhook/form/<slug:empresa_slug>/', webhook_form_lead, name='webhook_form_lead'),
    path('api/v1/webhook/form/<slug:empresa_slug>/pipelines/', webhook_form_pipelines, name='webhook_form_pipelines'),
    # Documentação API
    path('api/docs/webhook/', webhook_form_docs, name='webhook_form_docs'),
    # API genérica de eventos (multi-plataforma)
    path('api/v1/events/', receber_evento, name='api_events'),
]

# Servir arquivos de media em desenvolvimento
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
