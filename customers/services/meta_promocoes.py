"""
Servico de envio de mensagens promocionais via Meta WhatsApp Cloud API.
Templates aprovados para leads e carrinhos abandonados.
"""
import logging
from django.utils import timezone

from bling.meta_whatsapp import MetaWhatsAppClient
from customers.models import MensagemWhatsApp
from customers.services.wapi import formatar_telefone

logger = logging.getLogger(__name__)


def _get_meta_client(empresa):
    """Retorna MetaWhatsAppClient configurado para a empresa."""
    return MetaWhatsAppClient(
        phone_number_id=empresa.meta_phone_number_id,
        access_token=empresa.meta_access_token,
    )


def _registrar_mensagem(empresa, tipo, canal, nome, telefone,
                        template_name='', template_params=None,
                        mensagem_texto='', lead=None, cart=None,
                        customer=None, resultado=None):
    """Registra mensagem no historico centralizado."""
    success = resultado.get('success', False) if resultado else False
    response_data = resultado.get('response', {}) if resultado else {}

    # Extrair meta_message_id (wamid) da resposta da API
    meta_message_id = ''
    if success and response_data:
        messages = response_data.get('messages', [])
        if messages:
            meta_message_id = messages[0].get('id', '')

    return MensagemWhatsApp.objects.create(
        empresa=empresa,
        tipo=tipo,
        canal=canal,
        status='enviado' if success else 'falha',
        destinatario_nome=nome,
        destinatario_telefone=telefone,
        template_name=template_name,
        template_params=template_params or [],
        mensagem_texto=mensagem_texto,
        error_message=resultado.get('error', '') if resultado else '',
        api_response=response_data,
        meta_message_id=meta_message_id,
        lead=lead,
        cart=cart,
        customer=customer,
    )


def _cupom_params(empresa):
    """Retorna lista [cupom, desconto, validade] da empresa."""
    return [
        empresa.meta_cupom_codigo or 'cupom10',
        empresa.meta_cupom_desconto or '10',
        empresa.meta_cupom_validade or '',
    ]


def _build_template_params(empresa, template_name, nome):
    """
    Monta os parametros corretos para cada template.
    Templates com cupom: [nome, cupom, desconto, validade]
    Templates sem cupom (so nome): [nome]
    """
    # Templates que usam cupom (4 params: nome, cupom, desconto, validade)
    templates_com_cupom = [
        empresa.meta_template_lead_cliente,
        empresa.meta_template_lead_nao_cliente_cupom,
        empresa.meta_template_cliente_inativo,
    ]

    if template_name in templates_com_cupom:
        return [nome] + _cupom_params(empresa)

    # Templates simples (so nome) - ex: promocoes_tarragona_leads_nao_clientes
    return [nome]


def enviar_meta_lead(lead, empresa):
    """
    Envia template Meta para lead.
    - Lead ja cliente: meta_template_lead_cliente (com cupom)
    - Lead nao cliente: meta_template_lead_nao_cliente (sem cupom, so nome)
    """
    client = _get_meta_client(empresa)
    if not client.esta_configurado():
        logger.warning(f"Meta WhatsApp nao configurado para {empresa.nome}")
        return {'success': False, 'error': 'Meta WhatsApp nao configurado'}

    telefone = formatar_telefone(lead.whatsapp)
    if not telefone:
        return {'success': False, 'error': 'Lead sem WhatsApp'}

    nome = lead.nome.split()[0] if lead.nome else 'Cliente'
    is_cliente = lead.is_customer

    if is_cliente:
        template_name = empresa.meta_template_lead_cliente
        tipo = 'lead_cliente'
    else:
        template_name = empresa.meta_template_lead_nao_cliente
        tipo = 'lead'

    if not template_name:
        return {'success': False, 'error': f'Template Meta nao configurado para {tipo}'}

    params = _build_template_params(empresa, template_name, nome)

    resultado = client.enviar_template(telefone, template_name, params)

    # Registrar no historico
    _registrar_mensagem(
        empresa=empresa, tipo=tipo, canal='meta',
        nome=nome, telefone=telefone,
        template_name=template_name, template_params=params,
        lead=lead, customer=lead.related_customer,
        resultado=resultado,
    )

    # Atualizar lead
    if resultado['success']:
        lead.whatsapp_sent = True
        lead.whatsapp_sent_date = timezone.now()
        lead.whatsapp_auto_sent_count = (lead.whatsapp_auto_sent_count or 0) + 1
        lead.whatsapp_auto_status = 'sent_meta'
        lead.save(update_fields=[
            'whatsapp_sent', 'whatsapp_sent_date',
            'whatsapp_auto_sent_count', 'whatsapp_auto_status',
        ])
        logger.info(f"Meta template '{template_name}' enviado para lead {lead.nome} ({telefone})")
    else:
        lead.whatsapp_auto_status = 'failed_meta'
        lead.whatsapp_error_message = resultado.get('error', '')[:500]
        lead.save(update_fields=['whatsapp_auto_status', 'whatsapp_error_message'])

    return resultado


def enviar_meta_cart(cart, empresa):
    """
    Envia template Meta para carrinho abandonado.
    Suporta templates com cupom e sem cupom (com botao URL dinamica).

    Template sem cupom (ex: carrinho_abandonado_sem_cupom):
        Body: {{1}}=nome
        Botao URL: {{1}}=wcf_ac_token (session_id do carrinho)

    Template com cupom:
        Body: {{1}}=nome, {{2}}=cupom, {{3}}=desconto, {{4}}=validade
    """
    client = _get_meta_client(empresa)
    if not client.esta_configurado():
        logger.warning(f"Meta WhatsApp nao configurado para {empresa.nome}")
        return {'success': False, 'error': 'Meta WhatsApp nao configurado'}

    customer = cart.customer
    telefone = formatar_telefone(customer.phone or '')
    if not telefone:
        return {'success': False, 'error': 'Cliente sem telefone'}

    nome = customer.first_name.split()[0] if customer.first_name else 'Cliente'

    template_name = empresa.meta_template_cart
    if not template_name:
        return {'success': False, 'error': 'Template Meta cart nao configurado'}

    params = _build_template_params(empresa, template_name, nome)

    # Botao URL dinamica: usa session_id como wcf_ac_token
    button_url_params = None
    if cart.session_id:
        button_url_params = [cart.session_id]

    resultado = client.enviar_template(
        telefone, template_name, params,
        button_url_params=button_url_params,
    )

    # Registrar no historico
    _registrar_mensagem(
        empresa=empresa, tipo='cart', canal='meta',
        nome=nome, telefone=telefone,
        template_name=template_name, template_params=params,
        cart=cart, customer=customer,
        resultado=resultado,
    )

    # Atualizar cart
    if resultado['success']:
        cart.recovery_whatsapp_sent = True
        cart.recovery_whatsapp_date = timezone.now()
        cart.recovery_attempts = (cart.recovery_attempts or 0) + 1
        cart.save(update_fields=[
            'recovery_whatsapp_sent', 'recovery_whatsapp_date', 'recovery_attempts',
        ])
        logger.info(f"Meta cart recovery enviado para {customer.email} ({telefone})")
    else:
        logger.error(f"Erro Meta cart recovery {customer.email}: {resultado.get('error')}")

    return resultado


def enviar_meta_cliente_inativo(customer, empresa):
    """
    Envia template Meta para cliente inativo (reativacao com cupom).
    Template: meta_template_cliente_inativo (cupom_cliente_tarragona)
    Params: {{1}}=nome, {{2}}=cupom, {{3}}=desconto, {{4}}=validade
    """
    client = _get_meta_client(empresa)
    if not client.esta_configurado():
        return {'success': False, 'error': 'Meta WhatsApp nao configurado'}

    telefone = formatar_telefone(customer.phone or '')
    if not telefone:
        return {'success': False, 'error': 'Cliente sem telefone'}

    nome = customer.first_name.split()[0] if customer.first_name else 'Cliente'

    template_name = empresa.meta_template_cliente_inativo
    if not template_name:
        return {'success': False, 'error': 'Template Meta cliente inativo nao configurado'}

    params = _build_template_params(empresa, template_name, nome)

    resultado = client.enviar_template(telefone, template_name, params)

    _registrar_mensagem(
        empresa=empresa, tipo='cliente_inativo', canal='meta',
        nome=nome, telefone=telefone,
        template_name=template_name, template_params=params,
        customer=customer,
        resultado=resultado,
    )

    if resultado['success']:
        logger.info(f"Meta cliente inativo enviado para {customer.email} ({telefone})")
    else:
        logger.error(f"Erro Meta cliente inativo {customer.email}: {resultado.get('error')}")

    return resultado
