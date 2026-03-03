"""
Cliente W-API para envio de mensagens WhatsApp
Baseado no padrão do NeuraxoCheck (notifications/wapi.py)
"""
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class WAPIClient:
    """Cliente para API W-API (w-api.app)"""

    BASE_URL = 'https://api.w-api.app/v1'

    def __init__(self, token=None, instance=None):
        self.token = token or settings.WAPI_TOKEN
        self.instance = instance or settings.WAPI_INSTANCE

    def esta_configurado(self) -> bool:
        return bool(self.token and self.instance)

    def _headers(self):
        return {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json',
        }

    def verificar_status(self) -> dict:
        if not self.esta_configurado():
            return {'success': False, 'error': 'W-API não configurado'}
        try:
            response = requests.get(
                f"{self.BASE_URL}/instance/status-instance",
                params={'instanceId': self.instance},
                headers=self._headers(),
                timeout=30
            )
            if response.ok:
                data = response.json()
                return {'success': True, 'connected': data.get('connected', False), 'data': data}
            return {'success': False, 'error': response.text}
        except requests.exceptions.RequestException as e:
            return {'success': False, 'error': str(e)}

    def enviar_mensagem(self, telefone: str, mensagem: str, delay: int = 5) -> dict:
        """Envia mensagem de texto via W-API"""
        if not self.esta_configurado():
            return {'success': False, 'error': 'W-API não configurado'}

        try:
            response = requests.post(
                f"{self.BASE_URL}/message/send-text?instanceId={self.instance}",
                json={
                    'phone': telefone,
                    'message': mensagem,
                    'delayMessage': delay,
                    'disableTestMsg': True,
                },
                headers=self._headers(),
                timeout=30
            )

            if response.ok:
                logger.info(f"WhatsApp enviado para {telefone}")
                return {'success': True, 'response': response.json()}

            logger.error(f"Erro W-API {response.status_code}: {response.text}")
            return {'success': False, 'error': response.text}

        except requests.exceptions.RequestException as e:
            logger.error(f"Erro ao enviar WhatsApp: {e}")
            return {'success': False, 'error': str(e)}

    def enviar_imagem(self, telefone: str, image_url: str, caption: str = '') -> dict:
        """Envia imagem via W-API"""
        if not self.esta_configurado():
            return {'success': False, 'error': 'W-API não configurado'}

        try:
            response = requests.post(
                f"{self.BASE_URL}/message/send-image?instanceId={self.instance}",
                json={
                    'phone': telefone,
                    'image': image_url,
                    'caption': caption,
                },
                headers=self._headers(),
                timeout=30
            )

            if response.ok:
                return {'success': True, 'response': response.json()}
            return {'success': False, 'error': response.text}

        except requests.exceptions.RequestException as e:
            return {'success': False, 'error': str(e)}


# Mapa tipo de mensagem → campo FK na Empresa
INSTANCIA_MAP = {
    'lead': 'instancia_lead',
    'lead_cliente': 'instancia_lead_cliente',
    'cart': 'instancia_cart',
    'pedido_novo': 'instancia_pedido_novo',
    'pedido_processando': 'instancia_pedido_processando',
    'pedido_embalado': 'instancia_pedido_embalado',
    'pedido_transito': 'instancia_pedido_transito',
    'pedido_concluido': 'instancia_pedido_concluido',
    'pedido_cancelado': 'instancia_pedido_cancelado',
}

# Mapa status WooCommerce → chave do INSTANCIA_MAP
STATUS_INSTANCIA_MAP = {
    'processing': 'pedido_processando',
    'embalado': 'pedido_embalado',
    'em-transito': 'pedido_transito',
    'completed': 'pedido_concluido',
    'cancelled': 'pedido_cancelado',
}


def _get_wapi_client(empresa, tipo_mensagem):
    """
    Retorna WAPIClient da instância vinculada ao tipo de mensagem,
    ou fallback para credenciais default da empresa.
    """
    campo_fk = INSTANCIA_MAP.get(tipo_mensagem)
    instancia = getattr(empresa, campo_fk, None) if campo_fk else None
    if instancia and instancia.ativo:
        return WAPIClient(token=instancia.wapi_token, instance=instancia.wapi_instance)
    # Fallback: credenciais default da empresa
    return WAPIClient(
        token=empresa.wapi_token if empresa.wapi_token else None,
        instance=empresa.wapi_instance if empresa.wapi_instance else None,
    )


def formatar_telefone(telefone: str) -> str:
    """Formata telefone para W-API (apenas dígitos com 55)"""
    if not telefone:
        return ''
    numero = ''.join(filter(str.isdigit, telefone))
    if len(numero) == 11:
        numero = '55' + numero
    elif len(numero) == 10:
        numero = '55' + numero
    return numero


def enviar_whatsapp_lead(lead, is_customer: bool, empresa=None) -> dict:
    """
    Envia WhatsApp automático para lead novo.
    Mensagem diferente se já é cliente ou prospect.
    """
    telefone = formatar_telefone(lead.whatsapp)
    if not telefone:
        return {'success': False, 'error': 'Lead sem WhatsApp'}

    nome = lead.nome.split()[0] if lead.nome else 'Cliente'
    emp = empresa or lead.empresa

    if is_customer:
        template = emp.msg_whatsapp_lead_cliente if emp and emp.msg_whatsapp_lead_cliente else (
            "Olá {nome}, que bom ter você de volta! "
            "Vimos que você já comprou conosco e temos novidades especiais pra você. "
            "Posso te ajudar?"
        )
    else:
        template = emp.msg_whatsapp_lead if emp and emp.msg_whatsapp_lead else (
            "Olá {nome}, tudo bem?"
        )

    mensagem = template.replace('{nome}', nome)

    # Usar instância específica ou fallback para default
    tipo = 'lead_cliente' if is_customer else 'lead'
    client = _get_wapi_client(emp, tipo)

    if not client.esta_configurado():
        return {'success': False, 'error': 'W-API não configurado. Configure token e instância em Empresas > W-API WhatsApp.'}

    resultado = client.enviar_mensagem(telefone, mensagem)

    # Atualiza lead
    if resultado['success']:
        from django.utils import timezone
        lead.whatsapp_sent = True
        lead.whatsapp_sent_date = timezone.now()
        lead.whatsapp_auto_sent_count = (lead.whatsapp_auto_sent_count or 0) + 1
        lead.whatsapp_auto_status = 'sent'
        lead.save(update_fields=['whatsapp_sent', 'whatsapp_sent_date',
                                  'whatsapp_auto_sent_count', 'whatsapp_auto_status'])
        logger.info(f"WhatsApp enviado para lead {lead.nome} ({'cliente' if is_customer else 'prospect'})")
    else:
        lead.whatsapp_auto_status = 'failed'
        lead.whatsapp_error_message = resultado.get('error', '')[:500]
        lead.save(update_fields=['whatsapp_auto_status', 'whatsapp_error_message'])

    return resultado


def enviar_whatsapp_cart(cart, empresa=None) -> dict:
    """
    Envia WhatsApp de recuperação de carrinho abandonado via W-API.
    Usa credenciais da empresa (token/instance).
    """
    customer = cart.customer
    telefone = formatar_telefone(customer.phone or '')
    if not telefone:
        return {'success': False, 'error': 'Cliente sem telefone'}

    nome = customer.first_name.split()[0] if customer.first_name else 'Cliente'
    emp = empresa or cart.empresa

    template = emp.msg_whatsapp_cart if emp and emp.msg_whatsapp_cart else (
        "Olá {nome}, tudo bem?"
    )

    mensagem = template.replace('{nome}', nome)
    if cart.cart_total:
        mensagem = mensagem.replace('{valor}', f"R$ {cart.cart_total:,.2f}")

    # Usar instância específica ou fallback para default
    client = _get_wapi_client(emp, 'cart')

    if not client.esta_configurado():
        return {'success': False, 'error': 'W-API não configurado. Configure token e instância em Empresas > W-API WhatsApp.'}

    resultado = client.enviar_mensagem(telefone, mensagem)

    # Atualiza cart
    if resultado['success']:
        from django.utils import timezone
        cart.recovery_whatsapp_sent = True
        cart.recovery_whatsapp_date = timezone.now()
        cart.recovery_attempts = (cart.recovery_attempts or 0) + 1
        cart.save(update_fields=['recovery_whatsapp_sent', 'recovery_whatsapp_date', 'recovery_attempts'])
        logger.info(f"WhatsApp cart recovery enviado para {customer.email} ({telefone})")
    else:
        logger.error(f"Erro ao enviar WhatsApp cart recovery para {customer.email}: {resultado.get('error')}")

    return resultado


def enviar_whatsapp_pedido_novo(customer, order, empresa=None) -> dict:
    """
    Envia WhatsApp quando cliente faz uma compra nova.
    Mensagem com instruções do pedido.
    """
    telefone = formatar_telefone(customer.phone)
    if not telefone:
        return {'success': False, 'error': 'Cliente sem telefone'}

    nome = customer.first_name or 'Cliente'
    emp = empresa or customer.empresa

    template = emp.msg_whatsapp_pedido_novo if emp and emp.msg_whatsapp_pedido_novo else (
        "Olá {nome}! Recebemos seu pedido #{numero}. "
        "Obrigado pela compra! Em breve você receberá atualizações sobre o envio. "
        "Qualquer dúvida estamos à disposição."
    )

    mensagem = template.replace('{nome}', nome)
    mensagem = mensagem.replace('{numero}', str(order.order_number or order.order_id))
    mensagem = mensagem.replace('{valor}', f"R$ {order.total:,.2f}" if order.total else '')

    client = _get_wapi_client(emp, 'pedido_novo')
    return client.enviar_mensagem(telefone, mensagem)


STATUS_MSG_MAP = {
    'processing': 'msg_whatsapp_pedido_processando',
    'embalado': 'msg_whatsapp_pedido_embalado',
    'em-transito': 'msg_whatsapp_pedido_transito',
    'completed': 'msg_whatsapp_pedido_concluido',
    'cancelled': 'msg_whatsapp_pedido_cancelado',
}

STATUS_MSG_DEFAULTS = {
    'processing': 'Olá {nome}! Seu pagamento do pedido #{numero} foi confirmado! Estamos preparando seu pedido.',
    'embalado': 'Olá {nome}! Seu pedido #{numero} já foi embalado e saiu da fábrica! O código de rastreio será enviado para o seu email ainda hoje à noite.',
    'em-transito': 'Olá {nome}! Seu pedido #{numero} está em trânsito! Acompanhe pelo código de rastreio no seu email.',
    'completed': 'Olá {nome}! Seu pedido #{numero} foi entregue! Esperamos que goste. Qualquer dúvida estamos à disposição.',
    'cancelled': 'Olá {nome}, seu pedido #{numero} foi cancelado. Se precisar de ajuda, estamos à disposição.',
}


def enviar_whatsapp_pedido_status(customer, order, status, empresa=None) -> dict:
    """
    Envia WhatsApp baseado no status do pedido.
    Usa o template correspondente da empresa para o status.
    """
    if status not in STATUS_MSG_MAP:
        return {'success': False, 'error': f'Status {status} não tem mensagem configurada'}

    telefone = formatar_telefone(customer.phone)
    if not telefone:
        return {'success': False, 'error': 'Cliente sem telefone'}

    nome = customer.first_name or 'Cliente'
    emp = empresa or customer.empresa

    campo = STATUS_MSG_MAP[status]
    template = getattr(emp, campo, '') if emp else ''
    if not template:
        template = STATUS_MSG_DEFAULTS.get(status, '')

    mensagem = template.replace('{nome}', nome)
    mensagem = mensagem.replace('{numero}', str(order.order_number or order.order_id))
    mensagem = mensagem.replace('{valor}', f"R$ {order.total:,.2f}" if order.total else '')

    tipo = STATUS_INSTANCIA_MAP.get(status, '')
    client = _get_wapi_client(emp, tipo) if tipo else _get_wapi_client(emp, '')
    return client.enviar_mensagem(telefone, mensagem)


def enviar_whatsapp_pedido_embalado(customer, order, empresa=None) -> dict:
    """
    Envia WhatsApp quando pedido muda para 'embalado' no Bling.
    Informa que saiu da fábrica e rastreio chega à noite.
    """
    telefone = formatar_telefone(customer.phone)
    if not telefone:
        return {'success': False, 'error': 'Cliente sem telefone'}

    nome = customer.first_name or 'Cliente'
    emp = empresa or customer.empresa

    template = emp.msg_whatsapp_pedido_embalado if emp and emp.msg_whatsapp_pedido_embalado else (
        "Olá {nome}! Seu pedido #{numero} já foi embalado e saiu da fábrica! "
        "O código de rastreio será enviado para o seu email ainda hoje à noite. "
        "Obrigado pela preferência!"
    )

    mensagem = template.replace('{nome}', nome)
    mensagem = mensagem.replace('{numero}', str(order.order_number or order.order_id))

    client = _get_wapi_client(emp, 'pedido_embalado')
    return client.enviar_mensagem(telefone, mensagem)
