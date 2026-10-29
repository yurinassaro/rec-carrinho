"""
Envio de template pelo inbox (janela de 24h fechada).

O que precisa estar protegido: o nome do template vem do navegador, então só
pode sair o que está APROVADO na Meta daquela empresa; e template com variável
faltando é dinheiro gasto numa mensagem que a Meta recusa.
"""
import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase

from customers.models import MensagemWhatsApp
from customers.views_inbox import _params_do_template
from tenants.models import Empresa, EmpresaUsuario

APROVADOS = {
    'abertura_atendimento': {
        'header': '', 'body': 'Olá {{1}}! Aqui é a Tarragona.', 'footer': '', 'button_url': '',
    },
    'pedido_em_transito': {
        'header': 'Pedido {{2}}', 'body': 'Olá {{1}}! Seu pedido saiu.', 'footer': '', 'button_url': '',
    },
    'aviso_geral': {
        'header': '', 'body': 'Estamos de recesso esta semana.', 'footer': '', 'button_url': '',
    },
}


class ContarVariaveisTest(TestCase):
    def test_conta_pelo_maior_indice(self):
        self.assertEqual(_params_do_template(APROVADOS['abertura_atendimento']), 1)
        self.assertEqual(_params_do_template(APROVADOS['pedido_em_transito']), 2)
        self.assertEqual(_params_do_template(APROVADOS['aviso_geral']), 0)


class EnviarTemplatePeloInboxTest(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(
            nome='Loja', slug='loja', ativo=True, woo_webhook_secret='s',
            meta_phone_number_id='123', meta_access_token='tok', meta_waba_id='waba',
        )
        self.user = User.objects.create_user('atendente', password='x', is_staff=True)
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.user, is_default=True)
        self.client = Client()
        self.client.force_login(self.user)

    def enviar(self, corpo):
        return self.client.post(
            '/crm/inbox/enviar-template/', data=json.dumps(corpo),
            content_type='application/json',
        )

    @patch('customers.views_inbox._carregar_templates_meta', return_value=APROVADOS)
    def test_recusa_template_que_nao_esta_aprovado(self, _m):
        r = self.enviar({'telefone': '5516999990001', 'template': 'qualquer_coisa', 'params': ['Ana']})
        self.assertEqual(r.status_code, 400)
        self.assertIn('nao encontrado', r.json()['error'].lower())
        self.assertEqual(MensagemWhatsApp.objects.count(), 0)

    @patch('customers.views_inbox._carregar_templates_meta', return_value=APROVADOS)
    def test_recusa_quando_falta_variavel(self, _m):
        r = self.enviar({'telefone': '5516999990001', 'template': 'pedido_em_transito', 'params': ['Ana']})
        self.assertEqual(r.status_code, 400)
        self.assertIn('2', r.json()['error'])
        self.assertEqual(MensagemWhatsApp.objects.count(), 0)

    @patch('customers.views_inbox._carregar_templates_meta', return_value=APROVADOS)
    def test_variavel_so_com_espaco_nao_conta(self, _m):
        r = self.enviar({'telefone': '5516999990001', 'template': 'abertura_atendimento', 'params': ['   ']})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(MensagemWhatsApp.objects.count(), 0)

    @patch('customers.views_inbox._carregar_templates_meta', return_value=APROVADOS)
    def test_sem_telefone_recusa(self, _m):
        r = self.enviar({'telefone': '', 'template': 'aviso_geral', 'params': []})
        self.assertEqual(r.status_code, 400)

    # O idioma é lido da Meta dentro da view (import local) — patch na origem,
    # senão o teste sai na internet de verdade.
    @patch('customers.services.meta_promocoes._detectar_idioma_template', return_value='pt_BR')
    @patch('customers.views_inbox._carregar_templates_meta', return_value=APROVADOS)
    @patch('customers.views_inbox.MetaWhatsAppClient')
    def test_envia_e_guarda_no_historico(self, FakeClient, _m, _i):
        cliente = FakeClient.return_value
        cliente.esta_configurado.return_value = True
        cliente.enviar_template.return_value = {
            'success': True, 'response': {'messages': [{'id': 'wamid.ABC'}]},
        }

        r = self.enviar({
            'telefone': '5516999990001', 'template': 'abertura_atendimento', 'params': ['Ana'],
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['success'])

        msg = MensagemWhatsApp.objects.get(empresa=self.empresa)
        self.assertEqual(msg.template_name, 'abertura_atendimento')
        self.assertEqual(msg.template_params, ['Ana'])
        self.assertEqual(msg.meta_message_id, 'wamid.ABC')
        # o histórico guarda o texto já com a variável trocada, não o {{1}} cru
        self.assertIn('Ana', msg.mensagem_texto)
        # e a bolha volta pronta pra tela, sem segundo request
        self.assertEqual(r.json()['mensagem']['template_name'], 'abertura_atendimento')

    @patch('customers.views_inbox._carregar_templates_meta', return_value=APROVADOS)
    def test_exige_login(self, _m):
        self.client.logout()
        r = self.enviar({'telefone': '5516999990001', 'template': 'aviso_geral', 'params': []})
        self.assertIn(r.status_code, (302, 403))

    @patch('customers.views_inbox._carregar_templates_meta', return_value=APROVADOS)
    def test_lista_traz_os_aprovados_com_a_contagem(self, _m):
        r = self.client.get('/crm/inbox/api/templates/')
        self.assertEqual(r.status_code, 200)
        por_nome = {t['nome']: t for t in r.json()['templates']}
        self.assertEqual(por_nome['pedido_em_transito']['params'], 2)
        self.assertEqual(por_nome['aviso_geral']['params'], 0)
