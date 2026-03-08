"""
Cliente Meta WhatsApp Business Cloud API.
Envia mensagens template aprovadas pelo Meta.
Docs: https://developers.facebook.com/docs/whatsapp/cloud-api
"""
import logging
import requests

logger = logging.getLogger(__name__)


class MetaWhatsAppClient:
    """Cliente para Meta WhatsApp Cloud API."""

    BASE_URL = 'https://graph.facebook.com/v21.0'

    def __init__(self, phone_number_id, access_token):
        self.phone_number_id = phone_number_id
        self.access_token = access_token

    def esta_configurado(self):
        return bool(self.phone_number_id and self.access_token)

    def _headers(self):
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
        }

    def enviar_template(self, telefone, template_name, parametros,
                        language='pt_BR', button_url_params=None):
        """
        Envia mensagem template aprovada pelo Meta.

        Args:
            telefone: Número com código do país (ex: 5516996056762)
            template_name: Nome do template aprovado no WhatsApp Manager
            parametros: Lista de strings para substituir {{1}}, {{2}}, etc. no body
            language: Código do idioma do template
            button_url_params: Lista de strings para URLs dinâmicas dos botões.
                Ex: ['token123'] preenche {{1}} na URL do botão index 0.
        """
        if not self.esta_configurado():
            return {'success': False, 'error': 'Meta WhatsApp não configurado'}

        # Montar componentes do template
        components = []
        if parametros:
            body_params = [
                {'type': 'text', 'text': str(p)} for p in parametros
            ]
            components.append({
                'type': 'body',
                'parameters': body_params,
            })

        # Botões com URL dinâmica
        if button_url_params:
            for idx, param in enumerate(button_url_params):
                components.append({
                    'type': 'button',
                    'sub_type': 'url',
                    'index': str(idx),
                    'parameters': [{'type': 'text', 'text': str(param)}],
                })

        payload = {
            'messaging_product': 'whatsapp',
            'to': telefone,
            'type': 'template',
            'template': {
                'name': template_name,
                'language': {'code': language},
                'components': components,
            }
        }

        try:
            response = requests.post(
                f"{self.BASE_URL}/{self.phone_number_id}/messages",
                json=payload,
                headers=self._headers(),
                timeout=30,
            )

            if response.ok:
                data = response.json()
                logger.info(f"Meta WhatsApp template '{template_name}' enviado para {telefone}")
                return {'success': True, 'response': data}

            error_data = response.json() if response.content else {}
            error_msg = error_data.get('error', {}).get('message', response.text)
            logger.error(f"Erro Meta WhatsApp {response.status_code}: {error_msg}")
            return {'success': False, 'error': error_msg}

        except requests.exceptions.RequestException as e:
            logger.error(f"Erro ao enviar Meta WhatsApp: {e}")
            return {'success': False, 'error': str(e)}

    def enviar_texto(self, telefone, mensagem):
        """
        Envia mensagem de texto livre (apenas dentro da janela de 24h).
        Para uso fora da janela, use enviar_template().
        """
        if not self.esta_configurado():
            return {'success': False, 'error': 'Meta WhatsApp não configurado'}

        payload = {
            'messaging_product': 'whatsapp',
            'to': telefone,
            'type': 'text',
            'text': {'body': mensagem},
        }

        try:
            response = requests.post(
                f"{self.BASE_URL}/{self.phone_number_id}/messages",
                json=payload,
                headers=self._headers(),
                timeout=30,
            )

            if response.ok:
                logger.info(f"Meta WhatsApp texto enviado para {telefone}")
                return {'success': True, 'response': response.json()}

            error_data = response.json() if response.content else {}
            error_msg = error_data.get('error', {}).get('message', response.text)
            logger.error(f"Erro Meta WhatsApp {response.status_code}: {error_msg}")
            return {'success': False, 'error': error_msg}

        except requests.exceptions.RequestException as e:
            logger.error(f"Erro ao enviar Meta WhatsApp: {e}")
            return {'success': False, 'error': str(e)}
