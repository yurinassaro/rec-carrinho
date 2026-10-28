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

    def upload_midia(self, file_obj, mime_type, filename='upload.bin'):
        """
        Faz upload de arquivo para Meta e retorna media_id.

        Args:
            file_obj: arquivo (bytes ou file-like)
            mime_type: ex. 'image/jpeg', 'audio/mp3', 'audio/ogg'
            filename: nome do arquivo
        """
        if not self.esta_configurado():
            return {'success': False, 'error': 'Meta WhatsApp nao configurado'}

        try:
            response = requests.post(
                f"{self.BASE_URL}/{self.phone_number_id}/media",
                headers={'Authorization': f'Bearer {self.access_token}'},
                files={'file': (filename, file_obj, mime_type)},
                data={'messaging_product': 'whatsapp', 'type': mime_type},
                timeout=60,
            )
            if response.ok:
                data = response.json()
                return {'success': True, 'media_id': data.get('id', ''), 'response': data}
            error_msg = response.json().get('error', {}).get('message', response.text) if response.content else response.text
            logger.error(f"Erro upload midia Meta {response.status_code}: {error_msg}")
            return {'success': False, 'error': error_msg}
        except requests.exceptions.RequestException as e:
            logger.error(f"Erro ao fazer upload midia Meta: {e}")
            return {'success': False, 'error': str(e)}

    def enviar_midia(self, telefone, tipo, media_id, caption=None, responder_a=None):
        """
        Envia midia (image, audio, video, document) ja uploaded.

        Args:
            telefone: numero destinatario
            tipo: 'image' | 'audio' | 'video' | 'document'
            media_id: ID retornado por upload_midia
            caption: legenda (so image, video e document)
            responder_a: wamid da mensagem do cliente a citar (vira reply no app dele)
        """
        if not self.esta_configurado():
            return {'success': False, 'error': 'Meta WhatsApp nao configurado'}

        payload = {
            'messaging_product': 'whatsapp',
            'to': telefone,
            'type': tipo,
            tipo: {'id': media_id},
        }
        if caption and tipo in ('image', 'video', 'document'):
            payload[tipo]['caption'] = caption
        if responder_a:
            payload['context'] = {'message_id': responder_a}

        try:
            response = requests.post(
                f"{self.BASE_URL}/{self.phone_number_id}/messages",
                json=payload,
                headers=self._headers(),
                timeout=30,
            )
            if response.ok:
                logger.info(f"Meta WhatsApp {tipo} enviado para {telefone}")
                return {'success': True, 'response': response.json()}
            error_msg = response.json().get('error', {}).get('message', response.text) if response.content else response.text
            logger.error(f"Erro envio midia Meta {response.status_code}: {error_msg}")
            return {'success': False, 'error': error_msg}
        except requests.exceptions.RequestException as e:
            logger.error(f"Erro ao enviar midia Meta: {e}")
            return {'success': False, 'error': str(e)}

    def enviar_texto(self, telefone, mensagem, responder_a=None):
        """
        Envia mensagem de texto livre (apenas dentro da janela de 24h).
        Para uso fora da janela, use enviar_template().

        responder_a: wamid da mensagem do cliente. Com ele, o WhatsApp dele
        mostra a mensagem original citada em cima da resposta — o cliente vê
        exatamente a qual das perguntas estamos respondendo.
        """
        if not self.esta_configurado():
            return {'success': False, 'error': 'Meta WhatsApp não configurado'}

        payload = {
            'messaging_product': 'whatsapp',
            'to': telefone,
            'type': 'text',
            'text': {'body': mensagem},
        }
        if responder_a:
            payload['context'] = {'message_id': responder_a}

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
