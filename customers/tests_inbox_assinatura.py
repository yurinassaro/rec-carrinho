"""
Assinatura do atendente nas mensagens do inbox.

Duas pessoas dividem o mesmo número oficial (Yasmin de manhã, André à tarde),
então o cliente não sabe com quem está falando. A loja pode pedir pro inbox
pôr "Atendente Fulano" como título da mensagem.

O que precisa estar protegido: o nome vai PRO CLIENTE, então não pode ser
texto solto vindo do navegador — só quem está cadastrado na empresa.
"""
import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone

from customers.models import MensagemWhatsApp
from customers.views_inbox import _assinatura_atendente
from tenants.models import Empresa, EmpresaUsuario

ENVIO_OK = {'success': True, 'response': {'messages': [{'id': 'wamid.X'}]}}
TEL = '5516999990001'


class AssinaturaTest(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(
            nome='Loja', slug='loja', ativo=True, woo_webhook_secret='s',
            meta_phone_number_id='123', meta_access_token='tok', meta_waba_id='waba',
            atendente_manha='Yasmin', atendente_tarde='Andre', hora_troca_atendente=15,
            inbox_prefixo_atendente='sempre',
        )
        self.user = User.objects.create_user('atendente', password='x', is_staff=True)
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.user, is_default=True)
        self.client = Client()
        self.client.force_login(self.user)
        # Janela de 24h aberta: sem isso o envio livre é recusado.
        self.msg_cliente = MensagemWhatsApp.objects.create(
            empresa=self.empresa, tipo='resposta_cliente', canal='meta',
            status='recebido', destinatario_telefone=TEL, mensagem_texto='oi',
        )

    def enviar(self, corpo):
        return self.client.post(
            '/crm/inbox/enviar/', data=json.dumps(corpo), content_type='application/json',
        )

    # --- a regra pura -----------------------------------------------------

    def test_desligada_nao_assina(self):
        self.empresa.inbox_prefixo_atendente = ''
        self.assertEqual(_assinatura_atendente(self.empresa, 'Yasmin', [TEL]), '')

    def test_sem_nome_cadastrado_nao_assina(self):
        self.empresa.atendente_manha = ''
        self.empresa.atendente_tarde = ''
        self.assertEqual(_assinatura_atendente(self.empresa, '', [TEL]), '')

    def test_nome_de_fora_cai_no_plantao(self):
        """O nome vem da tela. Se não é um dos cadastrados, não vai pro cliente."""
        a = _assinatura_atendente(self.empresa, '<script>alert(1)</script>', [TEL])
        self.assertNotIn('script', a)
        self.assertIn(self.empresa.atendente_de_plantao, a)

    def test_nome_cadastrado_e_respeitado(self):
        self.assertEqual(_assinatura_atendente(self.empresa, 'Andre', [TEL]), '*Atendente Andre*')
        self.assertEqual(_assinatura_atendente(self.empresa, 'Yasmin', [TEL]), '*Atendente Yasmin*')

    # --- modo "primeira" --------------------------------------------------

    def test_modo_primeira_assina_a_primeira_e_cala_na_segunda(self):
        self.empresa.inbox_prefixo_atendente = 'primeira'
        self.assertEqual(_assinatura_atendente(self.empresa, 'Yasmin', [TEL]), '*Atendente Yasmin*')
        MensagemWhatsApp.objects.create(
            empresa=self.empresa, tipo='atendimento_humano', canal='meta',
            status='enviado', destinatario_telefone=TEL,
            mensagem_texto='*Atendente Yasmin*\nbom dia',
        )
        self.assertEqual(_assinatura_atendente(self.empresa, 'Yasmin', [TEL]), '')

    def test_modo_primeira_enxerga_mensagem_ja_entregue_ou_lida(self):
        """Segundos depois do envio o webhook da Meta troca o status pra
        'entregue' e depois 'lido'. Filtrar só por 'enviado' fazia o modo
        'primeira' se comportar como 'sempre' na prática."""
        self.empresa.inbox_prefixo_atendente = 'primeira'
        for status in ('entregue', 'lido'):
            MensagemWhatsApp.objects.filter(tipo='atendimento_humano').delete()
            MensagemWhatsApp.objects.create(
                empresa=self.empresa, tipo='atendimento_humano', canal='meta',
                status=status, destinatario_telefone=TEL,
                mensagem_texto='*Atendente Yasmin*\nbom dia',
            )
            self.assertEqual(
                _assinatura_atendente(self.empresa, 'Yasmin', [TEL]), '',
                f'com status={status} assinou de novo',
            )

    def test_modo_primeira_volta_a_assinar_quando_o_cliente_escreve_de_novo(self):
        self.empresa.inbox_prefixo_atendente = 'primeira'
        MensagemWhatsApp.objects.create(
            empresa=self.empresa, tipo='atendimento_humano', canal='meta',
            status='enviado', destinatario_telefone=TEL,
            mensagem_texto='*Atendente Yasmin*\nbom dia',
        )
        self.assertEqual(_assinatura_atendente(self.empresa, 'Yasmin', [TEL]), '')
        # Cliente volta horas depois: é uma conversa nova, assina de novo.
        MensagemWhatsApp.objects.create(
            empresa=self.empresa, tipo='resposta_cliente', canal='meta',
            status='recebido', destinatario_telefone=TEL, mensagem_texto='voltei',
        )
        self.assertEqual(_assinatura_atendente(self.empresa, 'Yasmin', [TEL]), '*Atendente Yasmin*')

    def test_modo_primeira_enxerga_assinatura_em_legenda_de_midia(self):
        """Em mídia o histórico começa com '[image] ' e a assinatura vem depois."""
        self.empresa.inbox_prefixo_atendente = 'primeira'
        MensagemWhatsApp.objects.create(
            empresa=self.empresa, tipo='atendimento_humano', canal='meta',
            status='enviado', destinatario_telefone=TEL,
            mensagem_texto='[image] *Atendente Yasmin*\nsegue a foto',
        )
        self.assertEqual(_assinatura_atendente(self.empresa, 'Yasmin', [TEL]), '')

    # --- ponta a ponta ----------------------------------------------------

    @patch('customers.views_inbox.MetaWhatsAppClient')
    def test_envio_sai_assinado_e_guarda_o_que_o_cliente_viu(self, MockClient):
        cli = MockClient.return_value
        cli.esta_configurado.return_value = True
        cli.enviar_texto.return_value = ENVIO_OK

        r = self.enviar({'telefone': TEL, 'texto': 'seu pedido saiu', 'atendente': 'Andre'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['success'])

        enviado = cli.enviar_texto.call_args[0][1]
        self.assertEqual(enviado, '*Atendente Andre*\nseu pedido saiu')

        msg = MensagemWhatsApp.objects.get(tipo='atendimento_humano')
        self.assertEqual(msg.mensagem_texto, '*Atendente Andre*\nseu pedido saiu')

    @patch('customers.views_inbox.MetaWhatsAppClient')
    def test_desligada_envia_o_texto_puro(self, MockClient):
        self.empresa.inbox_prefixo_atendente = ''
        self.empresa.save(update_fields=['inbox_prefixo_atendente'])
        cli = MockClient.return_value
        cli.esta_configurado.return_value = True
        cli.enviar_texto.return_value = ENVIO_OK

        self.enviar({'telefone': TEL, 'texto': 'seu pedido saiu'})
        self.assertEqual(cli.enviar_texto.call_args[0][1], 'seu pedido saiu')

    @patch('customers.views_inbox.MetaWhatsAppClient')
    def test_atendente_forjado_pelo_navegador_nao_chega_no_cliente(self, MockClient):
        cli = MockClient.return_value
        cli.esta_configurado.return_value = True
        cli.enviar_texto.return_value = ENVIO_OK

        self.enviar({'telefone': TEL, 'texto': 'oi', 'atendente': 'Banco do Brasil'})
        enviado = cli.enviar_texto.call_args[0][1]
        self.assertNotIn('Banco do Brasil', enviado)
        self.assertIn(self.empresa.atendente_de_plantao, enviado)


class JanelaFechadaTest(TestCase):
    """A assinatura não pode ter aberto caminho pra furar a janela de 24h."""

    def setUp(self):
        self.empresa = Empresa.objects.create(
            nome='Loja2', slug='loja2', ativo=True, woo_webhook_secret='s',
            meta_phone_number_id='123', meta_access_token='tok', meta_waba_id='waba',
            atendente_manha='Yasmin', inbox_prefixo_atendente='sempre',
        )
        self.user = User.objects.create_user('at2', password='x', is_staff=True)
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.user, is_default=True)
        self.client = Client()
        self.client.force_login(self.user)

    def test_sem_resposta_do_cliente_continua_recusando(self):
        antiga = MensagemWhatsApp.objects.create(
            empresa=self.empresa, tipo='resposta_cliente', canal='meta',
            status='recebido', destinatario_telefone=TEL, mensagem_texto='oi',
        )
        MensagemWhatsApp.objects.filter(id=antiga.id).update(
            created_at=timezone.now() - timedelta(hours=30)
        )
        r = self.client.post(
            '/crm/inbox/enviar/', data=json.dumps({'telefone': TEL, 'texto': 'oi'}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn('24h', r.json()['error'])
