"""
API endpoint para a extensão Chrome do WhatsApp Web.
Recebe contatos capturados do WhatsApp Web e salva como Lead no CRM.
"""
import hashlib
import logging
import re
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from tenants.models import Empresa
from customers.models import Lead, Customer

logger = logging.getLogger(__name__)


def _validar_api_key(request, empresa):
    """Valida a API key da extensão Chrome."""
    api_key = request.headers.get('X-API-Key', '')
    if not api_key:
        return False
    # API key = sha256(slug + woo_webhook_secret)
    # Reutiliza o webhook secret como seed para não criar campo novo
    expected = hashlib.sha256(
        f"{empresa.slug}:{empresa.woo_webhook_secret}".encode()
    ).hexdigest()[:32]
    return api_key == expected


def _limpar_telefone(telefone):
    """Limpa e formata telefone."""
    phone = re.sub(r'\D', '', telefone)
    if len(phone) < 10:
        return None
    if not phone.startswith('55'):
        phone = f'55{phone}'
    return phone


@csrf_exempt
@require_http_methods(["POST"])
def chrome_extension_lead(request, empresa_slug):
    """
    POST /api/v1/leads/chrome-extension/<slug>/
    Recebe contato do WhatsApp Web e salva como Lead.

    Headers: X-API-Key: <chave>
    Body JSON:
    {
        "telefone": "11999999999",
        "nome": "João Silva",
        "tags": ["whatsapp-web"]  // opcional
    }
    """
    import json

    # Buscar empresa
    try:
        empresa = Empresa.objects.get(slug=empresa_slug, ativo=True)
    except Empresa.DoesNotExist:
        return JsonResponse({'error': 'Empresa não encontrada'}, status=404)

    # Validar API key
    if not _validar_api_key(request, empresa):
        return JsonResponse({'error': 'API key inválida'}, status=401)

    # Parse body
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)

    telefone = data.get('telefone', '').strip()
    nome = data.get('nome', '').strip()
    tags = data.get('tags', [])

    if not telefone:
        return JsonResponse({'error': 'Telefone é obrigatório'}, status=400)
    if not nome:
        nome = 'Contato WhatsApp'

    # Limpar telefone
    telefone_limpo = _limpar_telefone(telefone)
    if not telefone_limpo:
        return JsonResponse({'error': 'Telefone inválido'}, status=400)

    # Verificar se já existe lead com esse telefone
    phone_suffix = telefone_limpo[-8:]
    lead_existente = Lead.objects.filter(
        empresa=empresa,
        whatsapp__endswith=phone_suffix,
    ).first()

    if lead_existente:
        return JsonResponse({
            'status': 'existing',
            'message': f'Lead já existe: {lead_existente.nome}',
            'lead_id': lead_existente.id,
            'lead_status': lead_existente.get_status_display(),
        })

    # Verificar se já é customer
    customer = Customer.objects.filter(
        empresa=empresa,
        phone__endswith=phone_suffix,
    ).first()

    is_customer = customer is not None
    lead_status = 'customer' if is_customer else 'new'

    # Criar form_id único
    form_id = f"chrome-{telefone_limpo}-{int(timezone.now().timestamp())}"

    # Criar lead
    lead = Lead.objects.create(
        empresa=empresa,
        form_id=form_id,
        nome=nome,
        whatsapp=telefone_limpo,
        numero_sapato='',
        status=lead_status,
        is_customer=is_customer,
        related_customer=customer,
        created_at=timezone.now(),
        notes=f"Capturado via extensão Chrome WhatsApp Web. Tags: {', '.join(tags)}" if tags else "Capturado via extensão Chrome WhatsApp Web.",
    )

    logger.info(f"[Chrome Extension] Lead criado: {lead.nome} - {lead.whatsapp} - empresa={empresa.slug}")

    return JsonResponse({
        'status': 'created',
        'message': f'Lead salvo: {nome}',
        'lead_id': lead.id,
        'is_customer': is_customer,
        'lead_status': lead.get_status_display(),
    }, status=201)


@csrf_exempt
@require_http_methods(["GET"])
def chrome_extension_check(request, empresa_slug):
    """
    GET /api/v1/leads/chrome-extension/<slug>/check/?telefone=11999999999
    Verifica se telefone já existe na base.
    """
    try:
        empresa = Empresa.objects.get(slug=empresa_slug, ativo=True)
    except Empresa.DoesNotExist:
        return JsonResponse({'error': 'Empresa não encontrada'}, status=404)

    if not _validar_api_key(request, empresa):
        return JsonResponse({'error': 'API key inválida'}, status=401)

    telefone = request.GET.get('telefone', '').strip()
    if not telefone:
        return JsonResponse({'error': 'Telefone é obrigatório'}, status=400)

    telefone_limpo = _limpar_telefone(telefone)
    if not telefone_limpo:
        return JsonResponse({'error': 'Telefone inválido'}, status=400)

    phone_suffix = telefone_limpo[-8:]

    # Verificar lead
    lead = Lead.objects.filter(
        empresa=empresa,
        whatsapp__endswith=phone_suffix,
    ).first()

    # Verificar customer
    customer = Customer.objects.filter(
        empresa=empresa,
        phone__endswith=phone_suffix,
    ).first()

    return JsonResponse({
        'exists': lead is not None or customer is not None,
        'is_lead': lead is not None,
        'is_customer': customer is not None,
        'lead_nome': lead.nome if lead else None,
        'lead_status': lead.get_status_display() if lead else None,
        'customer_nome': customer.full_name if customer else None,
        'customer_status': customer.get_status_display() if customer else None,
    })
