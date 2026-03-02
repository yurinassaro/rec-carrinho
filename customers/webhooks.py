"""
Webhooks do WooCommerce.
Recebe eventos de pedido criado e envia WhatsApp de boas-vindas via W-API.

Configurar no WooCommerce:
  WooCommerce > Settings > Advanced > Webhooks > Add Webhook
  - Name: Pedido Criado
  - Status: Active
  - Topic: Order created
  - Delivery URL: https://SEU-DOMINIO/webhooks/woo/<empresa-slug>/order-created/
  - Secret: (copiar de Empresa > Webhook Secret)
"""
import hashlib
import hmac
import base64
import json
import logging
import re

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from tenants.models import Empresa
from customers.models import Customer, Order
from customers.services.wapi import enviar_whatsapp_pedido_novo, formatar_telefone

logger = logging.getLogger(__name__)


def _verify_woo_signature(request, secret):
    """Verifica assinatura HMAC-SHA256 do WooCommerce webhook"""
    if not secret:
        return True  # sem secret configurado, aceita (dev)

    signature = request.headers.get('X-WC-Webhook-Signature', '')
    if not signature:
        return False

    expected = base64.b64encode(
        hmac.new(
            secret.encode('utf-8'),
            request.body,
            hashlib.sha256,
        ).digest()
    ).decode('utf-8')

    return hmac.compare_digest(signature, expected)


@csrf_exempt
@require_POST
def woo_order_created(request, empresa_slug):
    """
    Webhook: WooCommerce Order Created
    Recebe o payload do pedido, cria/atualiza Customer e Order,
    e envia WhatsApp de boas-vindas.
    """
    # 1. Buscar empresa
    try:
        empresa = Empresa.objects.get(slug=empresa_slug, ativo=True)
    except Empresa.DoesNotExist:
        return JsonResponse({'error': 'empresa not found'}, status=404)

    # 2. Verificar assinatura
    if not _verify_woo_signature(request, empresa.woo_webhook_secret):
        logger.warning(f'Webhook signature invalida para {empresa_slug}')
        return JsonResponse({'error': 'invalid signature'}, status=401)

    # 3. Parsear payload
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'invalid json'}, status=400)

    # WooCommerce envia um ping ao criar o webhook - responder OK
    if request.headers.get('X-WC-Webhook-Topic') == 'action.woocommerce_checkout_order_processed':
        pass  # continuar normalmente
    # Ping de verificacao
    if not payload.get('id'):
        return JsonResponse({'ok': True, 'message': 'ping received'})

    order_id = str(payload.get('id', ''))
    order_number = str(payload.get('number', order_id))
    status = payload.get('status', '')
    total = payload.get('total', '0')

    billing = payload.get('billing', {})
    email = billing.get('email', '')
    phone = billing.get('phone', '')
    first_name = billing.get('first_name', '')
    last_name = billing.get('last_name', '')
    address = billing.get('address_1', '')
    city = billing.get('city', '')
    state = billing.get('state', '')
    postcode = billing.get('postcode', '')

    if not email:
        return JsonResponse({'error': 'no email in billing'}, status=400)

    logger.info(f'Webhook order_created #{order_number} - {email} - {empresa_slug}')

    # 4. Criar/atualizar Customer
    customer_defaults = {
        'first_name': first_name,
        'last_name': last_name,
    }
    if phone:
        customer_defaults['phone'] = phone
    if address:
        customer_defaults['billing_address'] = address
    if city:
        customer_defaults['billing_city'] = city
    if state:
        customer_defaults['billing_state'] = state
    if postcode:
        customer_defaults['billing_postcode'] = postcode

    customer, _ = Customer.objects.update_or_create(
        empresa=empresa,
        email=email,
        defaults=customer_defaults,
    )

    # 5. Criar/atualizar Order
    try:
        total_decimal = float(total)
    except (ValueError, TypeError):
        total_decimal = 0

    items = payload.get('line_items', [])
    date_created = payload.get('date_created', '')

    from django.utils.dateparse import parse_datetime
    from django.utils import timezone as tz

    created_dt = parse_datetime(date_created) if date_created else tz.now()

    order_obj, order_created = Order.objects.update_or_create(
        empresa=empresa,
        order_id=order_id,
        defaults={
            'customer': customer,
            'order_number': order_number,
            'total': total_decimal,
            'status': status,
            'items_count': len(items),
            'created_at': created_dt,
            'payment_method': payload.get('payment_method', ''),
        }
    )

    # 6. Atualizar estatisticas do customer
    from django.db.models import Sum, Count
    stats = Order.objects.filter(customer=customer, empresa=empresa).aggregate(
        total_orders=Count('id'),
        total_spent=Sum('total'),
    )
    customer.total_orders = stats['total_orders'] or 0
    customer.total_spent = stats['total_spent'] or 0
    # Contar pedidos completados
    completed = Order.objects.filter(
        customer=customer, empresa=empresa,
        status__in=['completed', 'processing', 'on-hold']
    ).count()
    customer.completed_orders = completed
    customer.last_purchase = created_dt
    customer.save()

    # 7. Enviar WhatsApp de boas-vindas
    whatsapp_result = {'sent': False}
    if empresa.wapi_ativo and empresa.wapi_token and empresa.wapi_instance:
        telefone = formatar_telefone(phone)
        if telefone:
            result = enviar_whatsapp_pedido_novo(customer, order_obj, empresa=empresa)
            whatsapp_result = {
                'sent': result.get('success', False),
                'error': result.get('error', ''),
            }
            if result.get('success'):
                logger.info(f'WhatsApp boas-vindas enviado para {email} ({telefone})')
            else:
                logger.warning(f'Falha ao enviar WhatsApp para {email}: {result.get("error")}')
        else:
            whatsapp_result = {'sent': False, 'error': 'telefone invalido'}

    return JsonResponse({
        'ok': True,
        'order_id': order_id,
        'customer_email': email,
        'order_created': order_created,
        'whatsapp': whatsapp_result,
    })
