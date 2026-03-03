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
from customers.services.wapi import enviar_whatsapp_pedido_novo, enviar_whatsapp_pedido_status, STATUS_MSG_MAP, formatar_telefone

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
    try:
        return _process_woo_order(request, empresa_slug)
    except Exception as e:
        logger.error(f'Webhook EXCEPTION para {empresa_slug}: {type(e).__name__}: {e}', exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


def _process_woo_order(request, empresa_slug):
    """Processa o webhook de pedido do WooCommerce"""
    # Log headers para debug
    wc_topic = request.headers.get('X-WC-Webhook-Topic', '')
    wc_resource = request.headers.get('X-WC-Webhook-Resource', '')
    wc_event = request.headers.get('X-WC-Webhook-Event', '')
    content_type = request.headers.get('Content-Type', '')
    body_len = len(request.body) if request.body else 0
    logger.info(f'Webhook recebido de {empresa_slug}: topic={wc_topic}, resource={wc_resource}, event={wc_event}, content_type={content_type}, body_len={body_len}')

    # 1. Buscar empresa
    try:
        empresa = Empresa.objects.get(slug=empresa_slug, ativo=True)
    except Empresa.DoesNotExist:
        return JsonResponse({'error': 'empresa not found'}, status=404)

    # 2. Verificar assinatura (log warning se falhar, mas nao bloqueia)
    if not _verify_woo_signature(request, empresa.woo_webhook_secret):
        logger.warning(f'Webhook signature invalida para {empresa_slug} - processando mesmo assim')

    # 3. Parsear payload
    # WooCommerce ping pode vir como form-urlencoded (webhook_id=XX) em vez de JSON
    content_type = request.headers.get('Content-Type', '')
    if 'application/json' not in content_type:
        # Ping do WooCommerce em form-urlencoded - aceitar
        logger.info(f'Webhook ping (form-urlencoded) de {empresa_slug}: {request.body[:100]}')
        return JsonResponse({'ok': True, 'message': 'ping received'})

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError as e:
        logger.error(f'Webhook JSON invalido de {empresa_slug}: {e} - body preview: {request.body[:200]}')
        return JsonResponse({'error': 'invalid json'}, status=400)

    # Log payload keys para debug
    logger.info(f'Webhook payload keys: {list(payload.keys())[:15]}, id={payload.get("id")}, has_billing={bool(payload.get("billing"))}')

    # WooCommerce envia um ping ao salvar o webhook - responder OK
    # O ping pode vir com payload vazio, com webhook_id, ou com dados de outro resource
    # Aceitar ping de verificacao (qualquer payload sem billing ou sem id de order)
    if not payload.get('id') or wc_resource not in ('order', ''):
        logger.info(f'Webhook ping recebido de {empresa_slug} (topic={wc_topic}, resource={wc_resource})')
        return JsonResponse({'ok': True, 'message': 'ping received'})

    # Se tem billing, e um pedido - processar
    billing = payload.get('billing', {})
    email = billing.get('email', '')

    # Se nao tem billing/email, pode ser ping com id (ex: customer.created) - aceitar
    if not email:
        logger.info(f'Webhook recebido sem billing email de {empresa_slug} (topic={wc_topic})')
        return JsonResponse({'ok': True, 'message': 'received, no billing email'})

    order_id = str(payload.get('id', ''))
    order_number = str(payload.get('number', order_id))
    status = payload.get('status', '')
    total = payload.get('total', '0')
    phone = billing.get('phone', '')
    first_name = billing.get('first_name', '')
    last_name = billing.get('last_name', '')
    address = billing.get('address_1', '')
    city = billing.get('city', '')
    state = billing.get('state', '')
    postcode = billing.get('postcode', '')

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
    if empresa.wapi_ativo:
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


@csrf_exempt
@require_POST
def woo_order_updated(request, empresa_slug):
    """
    Webhook: WooCommerce Order Updated
    Recebe payload quando status de pedido muda,
    envia WhatsApp específico por status.
    """
    try:
        return _process_woo_order_updated(request, empresa_slug)
    except Exception as e:
        logger.error(f'Webhook order-updated EXCEPTION para {empresa_slug}: {type(e).__name__}: {e}', exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


def _process_woo_order_updated(request, empresa_slug):
    """Processa webhook de pedido atualizado do WooCommerce"""
    wc_topic = request.headers.get('X-WC-Webhook-Topic', '')
    wc_resource = request.headers.get('X-WC-Webhook-Resource', '')
    content_type = request.headers.get('Content-Type', '')
    body_len = len(request.body) if request.body else 0
    logger.info(f'Webhook order-updated de {empresa_slug}: topic={wc_topic}, resource={wc_resource}, content_type={content_type}, body_len={body_len}')

    # 1. Buscar empresa
    try:
        empresa = Empresa.objects.get(slug=empresa_slug, ativo=True)
    except Empresa.DoesNotExist:
        return JsonResponse({'error': 'empresa not found'}, status=404)

    # 2. Verificar assinatura
    if not _verify_woo_signature(request, empresa.woo_webhook_secret):
        logger.warning(f'Webhook order-updated signature invalida para {empresa_slug} - processando mesmo assim')

    # 3. Ping handling (form-urlencoded)
    if 'application/json' not in content_type:
        logger.info(f'Webhook order-updated ping (form-urlencoded) de {empresa_slug}')
        return JsonResponse({'ok': True, 'message': 'ping received'})

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError as e:
        logger.error(f'Webhook order-updated JSON invalido de {empresa_slug}: {e}')
        return JsonResponse({'error': 'invalid json'}, status=400)

    # Ping sem dados de order
    if not payload.get('id') or wc_resource not in ('order', ''):
        logger.info(f'Webhook order-updated ping de {empresa_slug} (topic={wc_topic})')
        return JsonResponse({'ok': True, 'message': 'ping received'})

    billing = payload.get('billing', {})
    email = billing.get('email', '')
    if not email:
        logger.info(f'Webhook order-updated sem billing email de {empresa_slug}')
        return JsonResponse({'ok': True, 'message': 'received, no billing email'})

    order_id = str(payload.get('id', ''))
    order_number = str(payload.get('number', order_id))
    new_status = payload.get('status', '')
    total = payload.get('total', '0')
    phone = billing.get('phone', '')
    first_name = billing.get('first_name', '')
    last_name = billing.get('last_name', '')
    address = billing.get('address_1', '')
    city = billing.get('city', '')
    state = billing.get('state', '')
    postcode = billing.get('postcode', '')

    logger.info(f'Webhook order-updated #{order_number} status={new_status} - {email} - {empresa_slug}')

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

    # 5. Buscar Order existente para comparar status
    try:
        total_decimal = float(total)
    except (ValueError, TypeError):
        total_decimal = 0

    items = payload.get('line_items', [])
    date_created = payload.get('date_created', '')

    from django.utils.dateparse import parse_datetime
    from django.utils import timezone as tz

    created_dt = parse_datetime(date_created) if date_created else tz.now()

    old_status = None
    try:
        existing_order = Order.objects.get(empresa=empresa, order_id=order_id)
        old_status = existing_order.status
    except Order.DoesNotExist:
        pass

    order_obj, order_created = Order.objects.update_or_create(
        empresa=empresa,
        order_id=order_id,
        defaults={
            'customer': customer,
            'order_number': order_number,
            'total': total_decimal,
            'status': new_status,
            'items_count': len(items),
            'created_at': created_dt,
            'payment_method': payload.get('payment_method', ''),
        }
    )

    # 6. Atualizar estatísticas do customer
    from django.db.models import Sum, Count
    stats = Order.objects.filter(customer=customer, empresa=empresa).aggregate(
        total_orders=Count('id'),
        total_spent=Sum('total'),
    )
    customer.total_orders = stats['total_orders'] or 0
    customer.total_spent = stats['total_spent'] or 0
    completed = Order.objects.filter(
        customer=customer, empresa=empresa,
        status__in=['completed', 'processing', 'on-hold']
    ).count()
    customer.completed_orders = completed
    customer.save()

    # 7. Enviar WhatsApp se status mudou e está no mapa
    whatsapp_result = {'sent': False}
    status_changed = old_status != new_status

    if status_changed and new_status in STATUS_MSG_MAP:
        if empresa.wapi_ativo:
            telefone = formatar_telefone(phone)
            if telefone:
                result = enviar_whatsapp_pedido_status(customer, order_obj, new_status, empresa=empresa)
                whatsapp_result = {
                    'sent': result.get('success', False),
                    'error': result.get('error', ''),
                }
                if result.get('success'):
                    logger.info(f'WhatsApp status={new_status} enviado para {email} ({telefone})')
                else:
                    logger.warning(f'Falha WhatsApp status={new_status} para {email}: {result.get("error")}')
            else:
                whatsapp_result = {'sent': False, 'error': 'telefone invalido'}
        else:
            whatsapp_result = {'sent': False, 'error': 'wapi não ativo'}
    elif not status_changed:
        logger.info(f'Order #{order_number} status não mudou ({new_status}), sem WhatsApp')
    elif new_status not in STATUS_MSG_MAP:
        logger.info(f'Order #{order_number} status={new_status} não tem mensagem configurada')

    return JsonResponse({
        'ok': True,
        'order_id': order_id,
        'customer_email': email,
        'old_status': old_status,
        'new_status': new_status,
        'status_changed': status_changed,
        'whatsapp': whatsapp_result,
    })
