"""
Webhook da Meta WhatsApp Cloud API.
Recebe eventos de mensagens recebidas, status de entrega, leitura, etc.

Configurar no Meta Business:
  Meta Business > WhatsApp > Configuracao > Webhooks
  - Callback URL: https://SEU-DOMINIO/webhooks/meta/
  - Verify Token: (mesmo valor de empresa.meta_webhook_verify_token)
  - Campos: messages, message_deliveries, message_reads
"""
import json
import logging

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

from tenants.models import Empresa
from customers.models import MensagemWhatsApp, Customer

logger = logging.getLogger(__name__)


@csrf_exempt
def meta_webhook(request):
    """
    Endpoint unico para Meta WhatsApp webhook.
    GET = verificacao (challenge)
    POST = eventos (mensagens recebidas, status updates)
    """
    if request.method == 'GET':
        return _verify_webhook(request)
    elif request.method == 'POST':
        return _process_webhook(request)
    return HttpResponse(status=405)


def _verify_webhook(request):
    """
    Meta envia GET com hub.mode, hub.verify_token e hub.challenge.
    Retornamos hub.challenge se o token bater.
    """
    mode = request.GET.get('hub.mode')
    token = request.GET.get('hub.verify_token')
    challenge = request.GET.get('hub.challenge')

    if mode != 'subscribe' or not token or not challenge:
        logger.warning('Meta webhook verify: parametros incompletos')
        return HttpResponse('Bad request', status=400)

    # Verificar token em qualquer empresa ativa
    empresa = Empresa.objects.filter(
        ativo=True,
        meta_webhook_verify_token=token,
    ).first()

    if empresa:
        logger.info(f'Meta webhook verificado para {empresa.slug}')
        return HttpResponse(challenge, content_type='text/plain')

    logger.warning(f'Meta webhook verify: token invalido ({token})')
    return HttpResponse('Forbidden', status=403)


def _process_webhook(request):
    """
    Processa eventos POST da Meta.
    Estrutura: { object: "whatsapp_business_account", entry: [...] }
    """
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'invalid json'}, status=400)

    if payload.get('object') != 'whatsapp_business_account':
        return HttpResponse('ok')

    for entry in payload.get('entry', []):
        for change in entry.get('changes', []):
            value = change.get('value', {})
            metadata = value.get('metadata', {})
            phone_number_id = metadata.get('phone_number_id', '')

            # Identificar empresa pelo phone_number_id
            empresa = Empresa.objects.filter(
                ativo=True,
                meta_phone_number_id=phone_number_id,
            ).first()

            if not empresa:
                logger.warning(
                    f'Meta webhook: phone_number_id {phone_number_id} '
                    f'nao encontrado em nenhuma empresa'
                )
                continue

            # Processar status updates (entregue, lido)
            for status in value.get('statuses', []):
                _process_status_update(status, empresa)

            # Processar mensagens recebidas (respostas dos clientes)
            for message in value.get('messages', []):
                contacts = value.get('contacts', [])
                _process_incoming_message(message, contacts, empresa)

    return HttpResponse('ok')


def _process_status_update(status_data, empresa):
    """
    Atualiza status de mensagem enviada: sent, delivered, read, failed.
    """
    wamid = status_data.get('id', '')
    status = status_data.get('status', '')
    timestamp = status_data.get('timestamp', '')

    if not wamid:
        return

    # Buscar mensagem original pelo meta_message_id
    msg = MensagemWhatsApp.objects.filter(
        empresa=empresa,
        meta_message_id=wamid,
    ).first()

    if not msg:
        return

    ts = timezone.datetime.fromtimestamp(
        int(timestamp), tz=timezone.utc
    ) if timestamp else timezone.now()

    if status == 'delivered':
        msg.status = 'entregue'
        msg.entregue_em = ts
        msg.save(update_fields=['status', 'entregue_em'])
        logger.info(f'Mensagem {wamid} entregue')

    elif status == 'read':
        msg.status = 'lido'
        msg.lido_em = ts
        msg.save(update_fields=['status', 'lido_em'])
        logger.info(f'Mensagem {wamid} lida')

    elif status == 'failed':
        errors = status_data.get('errors', [])
        error_msg = errors[0].get('message', '') if errors else ''
        msg.status = 'falha'
        msg.error_message = error_msg
        msg.save(update_fields=['status', 'error_message'])
        logger.error(f'Mensagem {wamid} falhou: {error_msg}')


def _process_incoming_message(message, contacts, empresa):
    """
    Processa mensagem recebida de um cliente.
    Vincula a resposta a mensagem original mais recente para aquele telefone.
    """
    from_number = message.get('from', '')  # ex: 5516996056762
    msg_type = message.get('type', '')
    timestamp = message.get('timestamp', '')
    context = message.get('context', {})  # se for reply, tem o id da msg original
    reply_to_wamid = context.get('id', '')  # wamid da mensagem que o cliente respondeu

    # Extrair texto da mensagem
    texto = ''
    if msg_type == 'text':
        texto = message.get('text', {}).get('body', '')
    elif msg_type == 'button':
        texto = message.get('button', {}).get('text', '')
    elif msg_type == 'interactive':
        interactive = message.get('interactive', {})
        if interactive.get('type') == 'button_reply':
            texto = interactive.get('button_reply', {}).get('title', '')
        elif interactive.get('type') == 'list_reply':
            texto = interactive.get('list_reply', {}).get('title', '')
    else:
        texto = f'[{msg_type}]'

    # Nome do contato
    nome = ''
    if contacts:
        profile = contacts[0].get('profile', {})
        nome = profile.get('name', '')

    ts = timezone.datetime.fromtimestamp(
        int(timestamp), tz=timezone.utc
    ) if timestamp else timezone.now()

    logger.info(
        f'[{empresa.slug}] Mensagem recebida de {from_number} ({nome}): '
        f'{texto[:100]}'
    )

    # Tentar vincular a mensagem original
    msg_original = None

    # 1. Se eh reply direto, buscar pelo wamid
    if reply_to_wamid:
        msg_original = MensagemWhatsApp.objects.filter(
            empresa=empresa,
            meta_message_id=reply_to_wamid,
        ).first()

    # 2. Senao, buscar a mensagem mais recente enviada para esse numero
    if not msg_original:
        msg_original = MensagemWhatsApp.objects.filter(
            empresa=empresa,
            destinatario_telefone=from_number,
            status__in=['enviado', 'entregue', 'lido'],
        ).order_by('-created_at').first()

    if msg_original:
        msg_original.respondido = True
        msg_original.respondido_em = ts
        msg_original.resposta_texto = texto[:2000]
        msg_original.save(update_fields=[
            'respondido', 'respondido_em', 'resposta_texto',
        ])
        logger.info(
            f'Resposta vinculada a mensagem {msg_original.id} '
            f'(tipo={msg_original.tipo}, template={msg_original.template_name})'
        )

    # Registrar mensagem recebida no historico
    # Buscar customer pelo telefone
    customer = Customer.objects.filter(
        empresa=empresa,
        phone__endswith=from_number[-8:],
    ).first()

    MensagemWhatsApp.objects.create(
        empresa=empresa,
        tipo='resposta_cliente',
        canal='meta',
        status='enviado',
        destinatario_nome=nome,
        destinatario_telefone=from_number,
        mensagem_texto=texto,
        meta_message_id=message.get('id', ''),
        api_response=message,
        customer=customer,
        lead=msg_original.lead if msg_original else None,
        cart=msg_original.cart if msg_original else None,
    )
