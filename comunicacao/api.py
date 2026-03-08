"""
API genérica de eventos.
POST /api/v1/events/ — recebe eventos de qualquer plataforma.

Autenticação: header X-API-Key com o slug da empresa + woo_webhook_secret.
Formato: X-API-Key: slug:secret
"""
import logging
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
import json

from tenants.models import Empresa
from comunicacao.models import EventoRecebido
from comunicacao.services.motor import avaliar_regras_para_gatilho

logger = logging.getLogger(__name__)

# Mapeamento tipo de evento → gatilho(s) de régua
EVENTO_TO_GATILHO = {
    'cart.abandoned': ['cart_abandoned'],
    'order.created': ['order_created'],
    'order.status_changed': [],  # resolvido dinamicamente
    'lead.created': ['lead_new'],
    'customer.created': ['customer_first_purchase'],
}

STATUS_TO_GATILHO = {
    'processing': 'order_processing',
    'embalado': 'order_shipped',
    'em-transito': 'order_in_transit',
    'completed': 'order_delivered',
    'cancelled': 'order_cancelled',
}


def _autenticar(request):
    """Autentica via X-API-Key header. Retorna Empresa ou None."""
    api_key = request.headers.get('X-API-Key', '')
    if ':' not in api_key:
        return None

    slug, secret = api_key.split(':', 1)
    try:
        empresa = Empresa.objects.get(slug=slug, ativo=True)
    except Empresa.DoesNotExist:
        return None

    if empresa.woo_webhook_secret and empresa.woo_webhook_secret == secret:
        return empresa

    return None


@csrf_exempt
@require_POST
def receber_evento(request):
    """
    POST /api/v1/events/

    Body JSON:
    {
        "type": "cart.abandoned",
        "platform": "woocommerce",
        "data": {
            "phone": "5516999999999",
            "name": "João",
            "email": "joao@email.com",
            "cart_total": 299.90,
            "session_id": "abc123",
            "items": [...],
            // ou para order:
            "order_id": "12345",
            "order_number": "12345",
            "total": 199.90,
            "status": "processing",
            "old_status": "pending",
            // ou para lead:
            "form_id": "form_123",
            "whatsapp": "16999999999",
            "nome": "João Silva",
        }
    }
    """
    empresa = _autenticar(request)
    if not empresa:
        return JsonResponse({'error': 'unauthorized'}, status=401)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'invalid json'}, status=400)

    tipo = body.get('type', '')
    plataforma = body.get('platform', 'api')
    data = body.get('data', {})

    if not tipo:
        return JsonResponse({'error': 'missing type'}, status=400)

    # Validar tipo
    tipos_validos = [c[0] for c in EventoRecebido.TIPO_CHOICES]
    if tipo not in tipos_validos:
        return JsonResponse({
            'error': f'invalid type. Valid: {tipos_validos}'
        }, status=400)

    # Registrar evento
    evento = EventoRecebido.objects.create(
        empresa=empresa,
        tipo=tipo,
        plataforma=plataforma,
        payload=data,
    )

    # Processar evento → disparar réguas
    resultados = _processar_evento(evento, empresa, tipo, data)

    evento.processado = True
    evento.processado_em = timezone.now()
    evento.save(update_fields=['processado', 'processado_em'])

    return JsonResponse({
        'ok': True,
        'event_id': evento.id,
        'rules_triggered': len([r for r in resultados if r[0]]),
    })


def _processar_evento(evento, empresa, tipo, data):
    """Processa evento e dispara réguas correspondentes."""
    telefone = data.get('phone', data.get('whatsapp', ''))
    nome = data.get('name', data.get('nome', 'Cliente'))

    # Resolver gatilhos
    gatilhos = list(EVENTO_TO_GATILHO.get(tipo, []))

    # Para order.status_changed, resolver gatilho pelo novo status
    if tipo == 'order.status_changed':
        new_status = data.get('status', '')
        gatilho = STATUS_TO_GATILHO.get(new_status)
        if gatilho:
            gatilhos.append(gatilho)

    # Tentar encontrar objetos existentes
    lead = None
    cart = None
    customer = None

    if data.get('email'):
        from customers.models import Customer
        customer = Customer.objects.filter(
            empresa=empresa, email=data['email'],
        ).first()

    if data.get('phone') and not customer:
        from customers.models import Customer
        from customers.services.wapi import formatar_telefone
        tel = formatar_telefone(data['phone'])
        if tel:
            customer = Customer.objects.filter(
                empresa=empresa, phone__endswith=tel[-8:],
            ).first()

    # Atualizar referências no evento
    if customer:
        evento.customer = customer
    evento.save(update_fields=['customer'])

    # Disparar réguas
    resultados = []
    for gatilho in gatilhos:
        r = avaliar_regras_para_gatilho(
            empresa, gatilho,
            lead=lead, cart=cart, customer=customer,
            telefone=telefone, nome=nome,
        )
        resultados.extend(r)

    return resultados
