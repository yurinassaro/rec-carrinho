"""
Views OAuth para autenticação com Bling API V3.
"""
import logging
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.urls import reverse

from tenants.models import Empresa
from bling.services import BlingClient

logger = logging.getLogger(__name__)


def _get_redirect_uri(request):
    """Monta a redirect URI absoluta para o callback."""
    return request.build_absolute_uri(reverse('bling_callback'))


@staff_member_required
def bling_authorize(request, empresa_slug):
    """Inicia fluxo OAuth redirecionando para o Bling."""
    empresa = get_object_or_404(Empresa, slug=empresa_slug)

    if not empresa.bling_client_id or not empresa.bling_client_secret:
        return HttpResponse(
            "Configure o Client ID e Client Secret do Bling primeiro.",
            status=400
        )

    client = BlingClient(empresa)
    url = client.get_authorization_url(redirect_uri=_get_redirect_uri(request))
    return HttpResponseRedirect(url)


@staff_member_required
def bling_callback(request):
    """Recebe o authorization code do Bling e troca por tokens."""
    code = request.GET.get('code')
    state = request.GET.get('state')  # slug da empresa

    if not code or not state:
        return HttpResponse("Parâmetros code/state ausentes.", status=400)

    empresa = get_object_or_404(Empresa, slug=state)
    client = BlingClient(empresa)

    try:
        client.exchange_code(code, redirect_uri=_get_redirect_uri(request))
        logger.info(f"Bling autorizado com sucesso para {empresa.nome}")
        # Redireciona para o admin da empresa
        return HttpResponseRedirect(
            reverse('admin:tenants_empresa_change', args=[empresa.pk])
        )
    except Exception as e:
        logger.error(f"Erro no callback Bling para {empresa.nome}: {e}")
        return HttpResponse(f"Erro ao autorizar Bling: {e}", status=500)
