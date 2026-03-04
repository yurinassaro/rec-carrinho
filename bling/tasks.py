"""
Celery tasks para sincronização Bling → WhatsApp.
"""
import logging
import random
import time

from celery import shared_task
from django.utils import timezone

from tenants.models import Empresa
from customers.services.wapi import formatar_telefone

logger = logging.getLogger(__name__)


def _extrair_telefone_pedido(pedido):
    """Extrai telefone do contato do pedido Bling."""
    contato = pedido.get('contato', {})
    # Bling pode retornar telefone ou celular
    telefone = contato.get('celular') or contato.get('fone') or ''
    return formatar_telefone(telefone)


def _extrair_nome_pedido(pedido):
    """Extrai primeiro nome do contato."""
    contato = pedido.get('contato', {})
    nome_completo = contato.get('nome', 'Cliente')
    return nome_completo.split()[0] if nome_completo else 'Cliente'


def _enviar_via_meta(empresa, telefone, nome, numero_pedido):
    """Envia via Meta Cloud API (template)."""
    from bling.meta_whatsapp import MetaWhatsAppClient

    client = MetaWhatsAppClient(
        phone_number_id=empresa.meta_phone_number_id,
        access_token=empresa.meta_access_token,
    )
    if not client.esta_configurado():
        return {'success': False, 'error': 'Meta WhatsApp não configurado'}

    template_name = empresa.meta_template_transito or 'pedido_em_transito'
    # Parâmetros do template: {{1}}=nome, {{2}}=numero_pedido
    return client.enviar_template(telefone, template_name, [nome, numero_pedido])


def _enviar_via_wapi(empresa, telefone, nome, numero_pedido):
    """Fallback: envia via W-API usando mensagem de texto."""
    from customers.services.wapi import _get_wapi_client, _msg_ativa

    if not _msg_ativa(empresa, 'pedido_transito'):
        return {'success': False, 'error': 'Mensagem pedido_transito desativada'}

    template = empresa.msg_whatsapp_pedido_transito or (
        'Olá {nome}! Seu pedido #{numero} está em trânsito!'
    )
    mensagem = template.replace('{nome}', nome).replace('{numero}', numero_pedido)

    client = _get_wapi_client(empresa, 'pedido_transito')
    if not client.esta_configurado():
        return {'success': False, 'error': 'W-API não configurado'}

    return client.enviar_mensagem(telefone, mensagem)


def sync_empresa_pedidos_transito(empresa, dry_run=False):
    """
    Sincroniza pedidos em trânsito de uma empresa.
    Retorna dict com estatísticas.
    """
    from bling.services import BlingClient
    from bling.models import BlingPedidoEnviado

    stats = {'total': 0, 'enviados': 0, 'ja_enviados': 0, 'erros': 0, 'sem_telefone': 0}

    if not empresa.bling_client_id or not empresa.bling_situacao_transito_id:
        logger.warning(f"[{empresa.nome}] Bling não configurado, pulando")
        return stats

    client = BlingClient(empresa)

    try:
        pedidos = client.get_pedidos_por_situacao(empresa.bling_situacao_transito_id)
    except Exception as e:
        logger.error(f"[{empresa.nome}] Erro ao buscar pedidos Bling: {e}")
        stats['erros'] += 1
        return stats

    stats['total'] = len(pedidos)
    logger.info(f"[{empresa.nome}] {len(pedidos)} pedidos em trânsito encontrados")

    # IDs já enviados para esta empresa
    ids_enviados = set(
        BlingPedidoEnviado.objects.filter(empresa=empresa)
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
            logger.info(f"[DRY-RUN] Enviaria WhatsApp para {nome} ({telefone}) - Pedido #{numero}")
            stats['enviados'] += 1
            continue

        # Tentar Meta Cloud API primeiro, fallback para W-API
        canal = 'meta'
        if empresa.meta_phone_number_id and empresa.meta_access_token:
            resultado = _enviar_via_meta(empresa, telefone, nome, numero)
        else:
            canal = 'wapi'
            resultado = _enviar_via_wapi(empresa, telefone, nome, numero)

        if resultado.get('success'):
            BlingPedidoEnviado.objects.create(
                empresa=empresa,
                bling_pedido_id=pedido_id,
                numero_pedido=numero,
                telefone=telefone,
                nome_cliente=nome,
                canal=canal,
            )
            stats['enviados'] += 1
            logger.info(f"[{empresa.nome}] WhatsApp enviado ({canal}) - Pedido #{numero} → {telefone}")
        else:
            stats['erros'] += 1
            logger.error(f"[{empresa.nome}] Erro Pedido #{numero}: {resultado.get('error')}")

        # Delay aleatório entre mensagens (45-120s)
        delay = random.uniform(45, 120)
        logger.debug(f"Aguardando {delay:.0f}s antes do próximo envio")
        time.sleep(delay)

    return stats


@shared_task(name='bling.sync_pedidos_em_transito')
def sync_pedidos_em_transito():
    """
    Task Celery: busca pedidos em trânsito no Bling e envia WhatsApp.
    Roda via Celery Beat a cada 30 minutos.
    """
    empresas = Empresa.objects.filter(
        ativo=True,
        bling_client_id__gt='',
        bling_situacao_transito_id__gt='',
    )

    resultados = {}
    for empresa in empresas:
        try:
            stats = sync_empresa_pedidos_transito(empresa)
            resultados[empresa.slug] = stats
            logger.info(
                f"[{empresa.nome}] Sync concluído: "
                f"{stats['enviados']} enviados, {stats['ja_enviados']} já enviados, "
                f"{stats['erros']} erros, {stats['sem_telefone']} sem telefone"
            )
        except Exception as e:
            logger.error(f"[{empresa.nome}] Erro fatal no sync: {e}")
            resultados[empresa.slug] = {'erro': str(e)}

    return resultados


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
