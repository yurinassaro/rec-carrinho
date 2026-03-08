"""
Sender: processa a FilaEnvio e envia mensagens via Meta ou W-API.
"""
import logging
from django.utils import timezone

from comunicacao.models import FilaEnvio, RegraComunicacao
from customers.models import MensagemWhatsApp
from bling.meta_whatsapp import MetaWhatsAppClient
from customers.services.wapi import (
    WAPIClient, _get_wapi_client, formatar_telefone,
)

logger = logging.getLogger(__name__)


def processar_fila(limit=100):
    """
    Processa itens pendentes da fila cujo horário de envio já passou.
    Chamado pelo Celery Beat a cada poucos minutos.
    """
    agora = timezone.now()

    itens = FilaEnvio.objects.filter(
        status='pendente',
        agendar_para__lte=agora,
    ).select_related(
        'empresa', 'regra', 'regra__instancia_wapi',
        'lead', 'cart', 'cart__customer', 'customer',
    ).order_by('agendar_para')[:limit]

    enviados = 0
    falhas = 0

    for item in itens:
        try:
            ok = _enviar_item(item)
            if ok:
                enviados += 1
            else:
                falhas += 1
        except Exception as e:
            logger.exception(f"Erro ao processar fila item {item.id}: {e}")
            item.status = 'falha'
            item.erro = str(e)[:500]
            item.processado_em = timezone.now()
            item.save(update_fields=['status', 'erro', 'processado_em'])
            falhas += 1

    if enviados or falhas:
        logger.info(f"Fila processada: {enviados} enviados, {falhas} falhas")

    return {'enviados': enviados, 'falhas': falhas}


def _enviar_item(item):
    """Envia um item da fila. Retorna True se sucesso."""
    regra = item.regra
    empresa = item.empresa

    # Re-verificar blacklist/capping (pode ter mudado desde enfileiramento)
    from comunicacao.services.motor import pode_enviar
    ok, motivo = pode_enviar(regra, item.telefone)
    if not ok:
        item.status = 'bloqueado'
        item.erro = motivo
        item.processado_em = timezone.now()
        item.save(update_fields=['status', 'erro', 'processado_em'])
        return False

    item.status = 'enviando'
    item.save(update_fields=['status'])

    # Resolver canal
    canal = regra.canal
    if canal == 'auto':
        canal = 'meta' if empresa.meta_phone_number_id and empresa.meta_access_token else 'wapi'

    if canal == 'meta':
        resultado = _enviar_via_meta(item, regra, empresa)
    else:
        resultado = _enviar_via_wapi(item, regra, empresa)

    sucesso = resultado.get('success', False)

    # Registrar mensagem no histórico
    msg = _registrar_mensagem(item, regra, empresa, canal, resultado)
    item.mensagem = msg

    if sucesso:
        item.status = 'enviado'
        # Atualizar estatísticas da régra
        RegraComunicacao.objects.filter(id=regra.id).update(
            total_enviados=models.F('total_enviados') + 1,
        )
    else:
        item.status = 'falha'
        item.erro = resultado.get('error', '')[:500]

    item.processado_em = timezone.now()
    item.save(update_fields=['status', 'erro', 'processado_em', 'mensagem'])

    return sucesso


def _enviar_via_meta(item, regra, empresa):
    """Envia via Meta Cloud API."""
    client = MetaWhatsAppClient(
        phone_number_id=empresa.meta_phone_number_id,
        access_token=empresa.meta_access_token,
    )
    if not client.esta_configurado():
        return {'success': False, 'error': 'Meta não configurado'}

    template = regra.template_meta
    if not template:
        return {'success': False, 'error': 'Template Meta não definido na régua'}

    # Montar parâmetros
    params = _build_params(regra, item)

    # Botão URL dinâmica
    button_url_params = None
    if regra.button_url_param and item.cart:
        val = getattr(item.cart, regra.button_url_param, None)
        if val:
            button_url_params = [str(val)]

    return client.enviar_template(
        item.telefone, template, params,
        button_url_params=button_url_params,
    )


def _enviar_via_wapi(item, regra, empresa):
    """Envia via W-API."""
    # Usar instância da régra ou fallback
    if regra.instancia_wapi and regra.instancia_wapi.ativo:
        client = WAPIClient(
            token=regra.instancia_wapi.wapi_token,
            instance=regra.instancia_wapi.wapi_instance,
        )
    else:
        client = WAPIClient(
            token=empresa.wapi_token,
            instance=empresa.wapi_instance,
        )

    if not client.esta_configurado():
        return {'success': False, 'error': 'W-API não configurado'}

    texto = regra.texto_wapi
    if not texto:
        return {'success': False, 'error': 'Texto W-API não definido na régua'}

    # Substituir variáveis
    cupom_params = regra.get_cupom_params()
    texto = texto.format(
        nome=item.nome,
        numero=getattr(item.cart, 'checkout_id', '') if item.cart else '',
        valor=str(item.cart.cart_total) if item.cart else '',
        cupom=cupom_params.get('cupom', ''),
        desconto=cupom_params.get('desconto', ''),
        validade=cupom_params.get('validade', ''),
    )

    return client.enviar_mensagem(item.telefone, texto)


def _build_params(regra, item):
    """Monta lista de parâmetros para template Meta baseado no mapeamento."""
    param_map = regra.template_params_map or ['nome']
    cupom = regra.get_cupom_params()

    valores = {
        'nome': item.nome,
        'cupom': cupom.get('cupom', regra.empresa.meta_cupom_codigo or ''),
        'desconto': cupom.get('desconto', regra.empresa.meta_cupom_desconto or ''),
        'validade': cupom.get('validade', regra.empresa.meta_cupom_validade or ''),
        'numero': '',
        'valor': '',
    }

    if item.cart:
        valores['numero'] = item.cart.checkout_id or ''
        valores['valor'] = str(item.cart.cart_total)
    elif item.customer:
        # Para pedidos, pegar do último order (se disponível)
        ultimo_order = item.customer.orders.order_by('-created_at').first()
        if ultimo_order:
            valores['numero'] = ultimo_order.order_number
            valores['valor'] = str(ultimo_order.total)

    return [valores.get(p, '') for p in param_map]


def _registrar_mensagem(item, regra, empresa, canal, resultado):
    """Registra mensagem no histórico centralizado."""
    success = resultado.get('success', False)
    response_data = resultado.get('response', {}) if isinstance(resultado.get('response'), dict) else {}

    meta_message_id = ''
    if success and response_data:
        messages = response_data.get('messages', [])
        if messages:
            meta_message_id = messages[0].get('id', '')

    # Mapear gatilho → tipo da MensagemWhatsApp
    tipo = _gatilho_to_tipo(regra.gatilho)

    return MensagemWhatsApp.objects.create(
        empresa=empresa,
        tipo=tipo,
        canal=canal,
        status='enviado' if success else 'falha',
        destinatario_nome=item.nome,
        destinatario_telefone=item.telefone,
        template_name=regra.template_meta if canal == 'meta' else '',
        template_params=_build_params(regra, item) if canal == 'meta' else [],
        mensagem_texto=regra.texto_wapi if canal == 'wapi' else '',
        error_message=resultado.get('error', '') if not success else '',
        api_response=response_data,
        meta_message_id=meta_message_id,
        lead=item.lead,
        cart=item.cart,
        customer=item.customer,
    )


def _gatilho_to_tipo(gatilho):
    """Mapeia gatilho da régra para tipo da MensagemWhatsApp."""
    mapping = {
        'cart_abandoned': 'cart',
        'cart_high_value': 'cart',
        'lead_new': 'lead',
        'lead_repeat_form': 'lead',
        'customer_inactive_30': 'cliente_inativo',
        'customer_inactive_60': 'cliente_inativo',
        'customer_inactive_90': 'cliente_inativo',
        'customer_first_purchase': 'pedido_novo',
        'customer_repeat_purchase': 'pedido_novo',
        'customer_vip': 'lead_cliente',
        'order_created': 'pedido_novo',
        'order_processing': 'pedido_processando',
        'order_shipped': 'pedido_embalado',
        'order_in_transit': 'pedido_transito',
        'order_delivered': 'pedido_concluido',
        'order_cancelled': 'pedido_cancelado',
        'manual': 'lead',
    }
    return mapping.get(gatilho, 'lead')


# Import necessário para F()
from django.db import models
