"""
Testes da sugestão da IA no inbox.

O que precisa estar garantido: a conversa chega à IA na ordem certa e com o
autor certo; a Ana cair não pode travar o atendente (cai pro Claude); e nada é
enviado sozinho — a rota só devolve texto.
"""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase

from customers.models import MensagemWhatsApp
from customers.services import copiloto
from customers.views_inbox import _conversa_para_ia
from tenants.models import Empresa, EmpresaUsuario


class ConversaParaIATest(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(
            nome='Loja', slug='loja', ativo=True, woo_webhook_secret='s',
        )
        self.tel = '5516999990001'

    def criar(self, tipo, texto='', template='', params=None):
        return MensagemWhatsApp.objects.create(
            empresa=self.empresa, canal='meta', tipo=tipo, status='entregue',
            destinatario_nome='Cliente', destinatario_telefone=self.tel,
            mensagem_texto=texto, template_name=template,
            template_params=params or [],
        )

    def test_marca_quem_falou_e_mantem_a_ordem(self):
        self.criar('promocao', 'Oi, tudo bem?')
        self.criar('resposta_cliente', 'tem bota 38?')
        self.criar('atendimento_humano', 'temos sim!')

        conversa = _conversa_para_ia(self.empresa, {self.tel})
        self.assertEqual(
            conversa,
            [
                {'autor': 'loja', 'texto': 'Oi, tudo bem?'},
                {'autor': 'cliente', 'texto': 'tem bota 38?'},
                {'autor': 'loja', 'texto': 'temos sim!'},
            ],
        )

    def test_descarta_mensagem_sem_texto(self):
        self.criar('resposta_cliente', '')
        self.criar('resposta_cliente', 'oi')
        self.assertEqual(len(_conversa_para_ia(self.empresa, {self.tel})), 1)

    def test_template_sem_texto_vira_marcador_legivel(self):
        self.criar('pedido_transito', '', template='pedido_em_transito')
        conversa = _conversa_para_ia(self.empresa, {self.tel})
        self.assertEqual(len(conversa), 1)
        self.assertIn('pedido_em_transito', conversa[0]['texto'])

    def test_pega_so_as_ultimas(self):
        for i in range(30):
            self.criar('resposta_cliente', f'msg {i}')
        conversa = _conversa_para_ia(self.empresa, {self.tel}, limite=5)
        self.assertEqual([c['texto'] for c in conversa],
                         ['msg 25', 'msg 26', 'msg 27', 'msg 28', 'msg 29'])


class CopilotoFallbackTest(TestCase):
    """A Ana fora do ar não pode deixar o atendente na mão."""

    def setUp(self):
        self.empresa = Empresa.objects.create(
            nome='Loja', slug='loja', ativo=True, woo_webhook_secret='s',
        )
        self.msgs = [{'autor': 'cliente', 'texto': 'tem bota 38?'}]

    @patch('customers.services.neuraxo_copilot.neuraxo_ativo', return_value=True)
    @patch('customers.services.neuraxo_copilot.sugerir_via_neuraxo')
    def test_usa_a_ana_quando_ela_responde(self, mock_ana, _ativo):
        mock_ana.return_value = {
            'resposta': 'Temos sim!', 'confianca': 'alta', 'observacao': '',
            'escalar': False, 'intent': 'produto', 'agente': 'Ana',
        }
        r = copiloto.sugerir(self.empresa, 'Fulano', self.msgs, '5516999990001')
        self.assertEqual(r['fonte'], 'neuraxo-agent')
        self.assertEqual(r['resposta'], 'Temos sim!')

    @patch('customers.services.neuraxo_copilot.neuraxo_ativo', return_value=True)
    @patch('customers.services.neuraxo_copilot.sugerir_via_neuraxo',
           side_effect=Exception('timeout'))
    def test_cai_pro_claude_quando_a_ana_falha(self, _ana, _ativo):
        class FakeSugestao:
            resposta, confianca, observacao = 'Temos sim.', 'media', ''

        with patch('customers.services.sugestao_ia.sugerir_resposta',
                   return_value=FakeSugestao()) as mock_claude:
            r = copiloto.sugerir(self.empresa, 'Fulano', self.msgs)
        self.assertEqual(r['fonte'], 'claude-local')
        self.assertTrue(mock_claude.called)

    @patch('customers.services.neuraxo_copilot.neuraxo_ativo', return_value=True)
    @patch('customers.services.neuraxo_copilot.sugerir_via_neuraxo',
           side_effect=Exception('fora do ar'))
    def test_sem_ana_e_sem_mensagens_avisa_em_vez_de_inventar(self, _ana, _ativo):
        with self.assertRaises(copiloto.CopilotoSemContexto):
            copiloto.sugerir(self.empresa, 'Fulano', [], '5516999990001')


class InboxSugerirViewTest(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(
            nome='Loja', slug='loja', ativo=True, woo_webhook_secret='s',
        )
        self.user = User.objects.create_user('atendente', password='x', is_staff=True)
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.user, is_default=True)
        self.client = Client()
        self.client.force_login(self.user)
        self.tel = '5516999990001'
        MensagemWhatsApp.objects.create(
            empresa=self.empresa, canal='meta', tipo='resposta_cliente', status='entregue',
            destinatario_nome='Fulano', destinatario_telefone=self.tel,
            mensagem_texto='tem bota 38?',
        )

    @patch('customers.services.copiloto.sugerir')
    def test_devolve_a_sugestao_sem_enviar_nada(self, mock_sugerir):
        mock_sugerir.return_value = {
            'resposta': 'Temos sim!', 'confianca': 'alta', 'observacao': '',
            'fonte': 'neuraxo-agent', 'agente': 'Ana', 'escalar': False,
        }
        antes = MensagemWhatsApp.objects.count()
        r = self.client.post('/crm/inbox/sugerir/', {'telefone': self.tel})

        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['resposta'], 'Temos sim!')
        # a sugestão NÃO vira mensagem: quem envia é o humano
        self.assertEqual(MensagemWhatsApp.objects.count(), antes)

    @patch('customers.services.copiloto.sugerir')
    def test_manda_a_conversa_e_o_nome_do_cliente(self, mock_sugerir):
        mock_sugerir.return_value = {
            'resposta': 'ok', 'confianca': 'alta', 'observacao': '',
            'fonte': 'claude-local', 'agente': '', 'escalar': False,
        }
        self.client.post('/crm/inbox/sugerir/', {'telefone': self.tel})

        _empresa, nome, mensagens, telefone = mock_sugerir.call_args[0]
        self.assertEqual(nome, 'Fulano')
        self.assertEqual(telefone, self.tel)
        self.assertEqual(mensagens, [{'autor': 'cliente', 'texto': 'tem bota 38?'}])

    @patch('customers.services.copiloto.sugerir',
           side_effect=copiloto.CopilotoErro('Erro na IA: cota'))
    def test_erro_da_ia_vira_502_com_mensagem(self, _m):
        r = self.client.post('/crm/inbox/sugerir/', {'telefone': self.tel})
        self.assertEqual(r.status_code, 502)
        self.assertIn('cota', r.json()['error'])

    def test_sem_telefone_da_400(self):
        r = self.client.post('/crm/inbox/sugerir/', {})
        self.assertEqual(r.status_code, 400)

    def test_exige_login(self):
        self.client.logout()
        r = self.client.post('/crm/inbox/sugerir/', {'telefone': self.tel})
        self.assertIn(r.status_code, (302, 403))

    def test_empresa_sem_o_modulo_de_ia_recebe_403(self):
        self.empresa.modulos = ['whatsapp_mapeamento']
        self.empresa.save(update_fields=['modulos'])
        r = self.client.post('/crm/inbox/sugerir/', {'telefone': self.tel})
        self.assertEqual(r.status_code, 403)
