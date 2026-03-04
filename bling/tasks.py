"""
Celery tasks para sincronização Bling → WhatsApp.
Suporta TODOS os status de pedido: processando, embalado, em-transito, concluido, cancelado.
"""
import logging
import random
import time

from celery import shared_task
from django.utils import timezone

from tenants.models import Empresa
from customers.services.wapi import formatar_telefone

logger = logging.getLogger(__name__)

# Mapa de status → campo da situação na Empresa + tipo de mensagem W-API
BLING_STATUS_MAP = {
    'processando': {
        'campo_situacao': 'bling_situacao_processando_id',
        'tipo_msg': 'pedido_processando',
        'campo_msg': 'msg_whatsapp_pedido_processando',
        'msg_default': 'Olá {nome}! Seu pagamento do pedido #{numero} foi confirmado!',
    },
    'embalado': {
        'campo_situacao': 'bling_situacao_embalado_id',
        'tipo_msg': 'pedido_embalado',
        'campo_msg': 'msg_whatsapp_pedido_embalado',
        'msg_default': 'Olá {nome}! Seu pedido #{numero} já foi embalado!',
    },
    'em-transito': {
        'campo_situacao': 'bling_situacao_transito_id',
        'tipo_msg': 'pedido_transito',
        'campo_msg': 'msg_whatsapp_pedido_transito',
        'msg_default': 'Olá {nome}! Seu pedido #{numero} está em trânsito!',
    },
    'concluido': {
        'campo_situacao': 'bling_situacao_concluido_id',
        'tipo_msg': 'pedido_concluido',
        'campo_msg': 'msg_whatsapp_pedido_concluido',
        'msg_default': 'Olá {nome}! Seu pedido #{numero} foi entregue!',
    },
    'cancelado': {
        'campo_situacao': 'bling_situacao_cancelado_id',
        'tipo_msg': 'pedido_cancelado',
        'campo_msg': 'msg_whatsapp_pedido_cancelado',
        'msg_default': 'Olá {nome}, seu pedido #{numero} foi cancelado.',
    },
}


def _extrair_telefone_pedido(pedido):
    """Extrai telefone do contato do pedido Bling."""
    contato = pedido.get('contato', {})
    telefone = contato.get('celular') or contato.get('fone') or ''
    return formatar_telefone(telefone)


def _extrair_nome_pedido(pedido):
    """Extrai primeiro nome do contato."""
    contato = pedido.get('contato', {})
    nome_completo = contato.get('nome', 'Cliente')
    return nome_completo.split()[0] if nome_completo else 'Cliente'


def _enviar_via_wapi(empresa, telefone, nome, numero_pedido, status):
    """Envia via W-API usando mensagem configurada para o status."""
    from customers.services.wapi import _get_wapi_client, _msg_ativa

    config = BLING_STATUS_MAP.get(status)
    if not config:
        return {'success': False, 'error': f'Status desconhecido: {status}'}

    tipo_msg = config['tipo_msg']

    if not _msg_ativa(empresa, tipo_msg):
        return {'success': False, 'error': f'Mensagem {tipo_msg} desativada'}

    template = getattr(empresa, config['campo_msg'], '') or config['msg_default']
    mensagem = template.replace('{nome}', nome).replace('{numero}', numero_pedido)

    client = _get_wapi_client(empresa, tipo_msg)
    if not client.esta_configurado():
        return {'success': False, 'error': 'W-API não configurado'}

    return client.enviar_mensagem(telefone, mensagem)


def sync_empresa_pedidos_por_status(empresa, status, dry_run=False):
    """
    Sincroniza pedidos de um status específico de uma empresa.
    Retorna dict com estatísticas.
    """
    from bling.services import BlingClient
    from bling.models import BlingPedidoEnviado

    stats = {'status': status, 'total': 0, 'enviados': 0, 'ja_enviados': 0, 'erros': 0, 'sem_telefone': 0}

    config = BLING_STATUS_MAP.get(status)
    if not config:
        logger.error(f"[{empresa.nome}] Status '{status}' não reconhecido")
        return stats

    situacao_id = getattr(empresa, config['campo_situacao'], '')
    if not empresa.bling_client_id or not situacao_id:
        logger.debug(f"[{empresa.nome}] Bling não configurado para status '{status}'")
        return stats

    client = BlingClient(empresa)

    try:
        pedidos = client.get_pedidos_por_situacao(situacao_id)
    except Exception as e:
        logger.error(f"[{empresa.nome}] Erro ao buscar pedidos Bling (status={status}): {e}")
        stats['erros'] += 1
        return stats

    stats['total'] = len(pedidos)
    logger.info(f"[{empresa.nome}] {len(pedidos)} pedidos '{status}' encontrados")

    # IDs já enviados para esta empresa + status
    ids_enviados = set(
        BlingPedidoEnviado.objects.filter(empresa=empresa, status=status)
        .values_list('bling_pedido_id', flat=True)
    )

    for pedido in pedidos:
        pedido_id = str(pedido.get('id', ''))
        numero = str(pedido.get('numero', ''))

        if pedido_id in ids_enviados:
            stats['ja_enviados'] += 1
            continue

        telefone = _extrair_telefone_pedido(pedido)
        if not telefone:
            logger.warning(f"[{empresa.nome}] Pedido #{numero} sem telefone")
            stats['sem_telefone'] += 1
            continue

        nome = _extrair_nome_pedido(pedido)

        if dry_run:
            logger.info(f"[DRY-RUN] [{status}] Enviaria WhatsApp para {nome} ({telefone}) - Pedido #{numero}")
            stats['enviados'] += 1
            continue

        resultado = _enviar_via_wapi(empresa, telefone, nome, numero, status)

        if resultado.get('success'):
            BlingPedidoEnviado.objects.create(
                empresa=empresa,
                bling_pedido_id=pedido_id,
                numero_pedido=numero,
                telefone=telefone,
                nome_cliente=nome,
                status=status,
                canal='wapi',
            )
            stats['enviados'] += 1
            logger.info(f"[{empresa.nome}] WhatsApp enviado [{status}] - Pedido #{numero} → {telefone}")
        else:
            stats['erros'] += 1
            logger.error(f"[{empresa.nome}] Erro Pedido #{numero} [{status}]: {resultado.get('error')}")

        # Delay aleatório entre mensagens (45-120s)
        delay = random.uniform(45, 120)
        logger.debug(f"Aguardando {delay:.0f}s antes do próximo envio")
        time.sleep(delay)

    return stats


# Manter compatibilidade com código existente
def sync_empresa_pedidos_transito(empresa, dry_run=False):
    """Wrapper de compatibilidade. Sincroniza apenas pedidos em trânsito."""
    return sync_empresa_pedidos_por_status(empresa, 'em-transito', dry_run=dry_run)


@shared_task(name='bling.sync_todos_status')
def sync_todos_status_bling():
    """
    Task Celery: busca pedidos de TODOS os status configurados no Bling e envia WhatsApp.
    Roda via Celery Beat a cada 30 minutos.
    """
    empresas = Empresa.objects.filter(
        ativo=True,
        bling_client_id__gt='',
    )

    resultados = {}
    for empresa in empresas:
        resultados[empresa.slug] = {}
        for status, config in BLING_STATUS_MAP.items():
            situacao_id = getattr(empresa, config['campo_situacao'], '')
            if not situacao_id:
                continue  # Status não configurado para esta empresa
            try:
                stats = sync_empresa_pedidos_por_status(empresa, status)
                resultados[empresa.slug][status] = stats
                logger.info(
                    f"[{empresa.nome}] [{status}] Sync concluído: "
                    f"{stats['enviados']} enviados, {stats['ja_enviados']} já enviados, "
                    f"{stats['erros']} erros, {stats['sem_telefone']} sem telefone"
                )
            except Exception as e:
                logger.error(f"[{empresa.nome}] [{status}] Erro fatal no sync: {e}")
                resultados[empresa.slug][status] = {'erro': str(e)}

    return resultados


@shared_task(name='bling.sync_pedidos_em_transito')
def sync_pedidos_em_transito():
    """
    Task Celery legada: apenas em trânsito.
    Mantida para compatibilidade com Celery Beat existente.
    Redireciona para sync_todos_status_bling.
    """
    return sync_todos_status_bling()


@shared_task(name='bling.refresh_tokens')
def refresh_bling_tokens():
    """
    Task Celery: renova tokens Bling prestes a expirar.
    Roda via Celery Beat a cada 30 minutos.
    """
    from bling.models import BlingToken
    from bling.services import BlingClient
    from datetime import timedelta

    # Tokens que expiram nos próximos 30 minutos
    threshold = timezone.now() + timedelta(minutes=30)
    tokens = BlingToken.objects.filter(expires_at__lte=threshold).select_related('empresa')

    for token in tokens:
        try:
            client = BlingClient(token.empresa)
            client.refresh_access_token()
            logger.info(f"Token Bling renovado para {token.empresa.nome}")
        except Exception as e:
            logger.error(f"Erro ao renovar token Bling para {token.empresa.nome}: {e}")
