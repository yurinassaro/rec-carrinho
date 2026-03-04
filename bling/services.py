"""
Cliente Bling API V3 com OAuth2 e auto-refresh de tokens.
Docs: https://developer.bling.com.br/api
"""
import logging
import base64
from datetime import timedelta

import requests
from django.utils import timezone

logger = logging.getLogger(__name__)

BLING_API_BASE = 'https://www.bling.com.br/Api/v3'
BLING_OAUTH_AUTHORIZE = 'https://www.bling.com.br/Api/v3/oauth/authorize'
BLING_OAUTH_TOKEN = 'https://www.bling.com.br/Api/v3/oauth/token'


class BlingClient:
    """Cliente para Bling API V3 com OAuth2."""

    def __init__(self, empresa):
        self.empresa = empresa
        self.client_id = empresa.bling_client_id
        self.client_secret = empresa.bling_client_secret
        self._token = None

    def _load_token(self):
        """Carrega token do banco."""
        if self._token is None:
            try:
                self._token = self.empresa.bling_token
            except Exception:
                self._token = None
        return self._token

    def get_authorization_url(self, redirect_uri):
        """Retorna URL para o usuário autorizar o app no Bling."""
        return (
            f"{BLING_OAUTH_AUTHORIZE}"
            f"?response_type=code"
            f"&client_id={self.client_id}"
            f"&redirect_uri={redirect_uri}"
            f"&state={self.empresa.slug}"
        )

    def _basic_auth(self):
        """Header Basic auth para troca/refresh de token."""
        credentials = f"{self.client_id}:{self.client_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"

    def exchange_code(self, code, redirect_uri):
        """Troca authorization code por access/refresh tokens."""
        response = requests.post(
            BLING_OAUTH_TOKEN,
            headers={
                'Authorization': self._basic_auth(),
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            data={
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': redirect_uri,
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        self._save_tokens(data)
        logger.info(f"Bling OAuth tokens salvos para {self.empresa.nome}")
        return data

    def refresh_access_token(self):
        """Renova access token usando refresh token."""
        token = self._load_token()
        if not token:
            raise ValueError(f"Nenhum token Bling encontrado para {self.empresa.nome}")

        response = requests.post(
            BLING_OAUTH_TOKEN,
            headers={
                'Authorization': self._basic_auth(),
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            data={
                'grant_type': 'refresh_token',
                'refresh_token': token.refresh_token,
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        self._save_tokens(data)
        logger.info(f"Bling token renovado para {self.empresa.nome}")
        return data

    def _save_tokens(self, data):
        """Salva tokens no banco."""
        from bling.models import BlingToken

        expires_in = data.get('expires_in', 21600)  # default 6h
        expires_at = timezone.now() + timedelta(seconds=expires_in)

        token, created = BlingToken.objects.update_or_create(
            empresa=self.empresa,
            defaults={
                'access_token': data['access_token'],
                'refresh_token': data['refresh_token'],
                'expires_at': expires_at,
            }
        )
        self._token = token

    def _get_access_token(self):
        """Retorna access token válido, renovando se necessário."""
        token = self._load_token()
        if not token:
            raise ValueError(f"Bling não autorizado para {self.empresa.nome}")

        # Renovar se expira em menos de 5 minutos
        if token.expires_at <= timezone.now() + timedelta(minutes=5):
            self.refresh_access_token()
            token = self._load_token()

        return token.access_token

    def _request(self, method, endpoint, **kwargs):
        """Request autenticado com auto-refresh."""
        url = f"{BLING_API_BASE}{endpoint}"
        headers = kwargs.pop('headers', {})
        headers['Authorization'] = f"Bearer {self._get_access_token()}"

        response = requests.request(
            method, url, headers=headers, timeout=30, **kwargs
        )

        # Token expirado - tentar refresh uma vez
        if response.status_code == 401:
            logger.warning(f"Bling 401 para {self.empresa.nome}, renovando token...")
            self.refresh_access_token()
            headers['Authorization'] = f"Bearer {self._get_access_token()}"
            response = requests.request(
                method, url, headers=headers, timeout=30, **kwargs
            )

        response.raise_for_status()
        return response.json()

    def get_pedidos_por_situacao(self, situacao_id, pagina=1):
        """
        Busca pedidos de venda por situação.
        Retorna lista de pedidos do Bling.
        """
        data = self._request(
            'GET',
            '/pedidos/vendas',
            params={
                'idsSituacoes[]': situacao_id,
                'pagina': pagina,
                'limite': 100,
            }
        )
        return data.get('data', [])

    def get_pedido_detalhe(self, pedido_id):
        """Busca detalhes de um pedido específico."""
        data = self._request('GET', f'/pedidos/vendas/{pedido_id}')
        return data.get('data', {})

    def get_situacoes(self):
        """Lista todas as situações de venda (útil para descobrir IDs)."""
        data = self._request('GET', '/situacoes/vendas')
        return data.get('data', [])
