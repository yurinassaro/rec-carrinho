"""
Testes das mensagens rápidas do inbox (RespostaRapida).

O que precisa estar protegido: uma empresa nunca ver a resposta pronta da outra,
e a lista se reorganizar pelas mais usadas.
"""
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase

from customers.models import RespostaRapida
from tenants.models import Empresa, EmpresaUsuario


class RespostasRapidasAPITest(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(
            nome='Loja', slug='loja', ativo=True, woo_webhook_secret='s',
        )
        self.outra = Empresa.objects.create(
            nome='Outra', slug='outra', ativo=True, woo_webhook_secret='s2',
        )
        self.user = User.objects.create_user('atendente', password='x', is_staff=True)
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.user, is_default=True)
        self.client = Client()
        self.client.force_login(self.user)

        self.minha = RespostaRapida.objects.create(
            empresa=self.empresa, titulo='Qual o prazo?', texto='São 5 dias úteis.',
        )
        RespostaRapida.objects.create(
            empresa=self.empresa, titulo='Desativada', texto='não deve aparecer', ativo=False,
        )
        self.da_outra = RespostaRapida.objects.create(
            empresa=self.outra, titulo='Segredo da outra', texto='confidencial',
        )

    def listar(self):
        r = self.client.get('/crm/inbox/api/respostas/')
        self.assertEqual(r.status_code, 200)
        return r.json()['respostas']

    def test_lista_so_as_ativas_da_minha_empresa(self):
        titulos = [x['titulo'] for x in self.listar()]
        self.assertEqual(titulos, ['Qual o prazo?'])

    def test_nao_vaza_resposta_de_outra_empresa(self):
        textos = [x['texto'] for x in self.listar()]
        self.assertNotIn('confidencial', textos)

    def test_contar_uso_incrementa(self):
        r = self.client.post('/crm/inbox/api/respostas/usada/', {'id': self.minha.id})
        self.assertEqual(r.status_code, 200)
        self.minha.refresh_from_db()
        self.assertEqual(self.minha.usos, 1)

    def test_nao_conta_uso_de_resposta_de_outra_empresa(self):
        self.client.post('/crm/inbox/api/respostas/usada/', {'id': self.da_outra.id})
        self.da_outra.refresh_from_db()
        self.assertEqual(self.da_outra.usos, 0)

    def test_mais_usadas_vem_primeiro(self):
        segunda = RespostaRapida.objects.create(
            empresa=self.empresa, titulo='A primeira do alfabeto', texto='oi', usos=9,
        )
        titulos = [x['titulo'] for x in self.listar()]
        self.assertEqual(titulos[0], segunda.titulo)

    def test_exige_login(self):
        self.client.logout()
        r = self.client.get('/crm/inbox/api/respostas/')
        self.assertIn(r.status_code, (302, 403))


class ImportarRespostasRapidasTest(TestCase):
    """O comando reimporta sem duplicar — dá pra exportar do zap de novo depois."""

    def setUp(self):
        self.empresa = Empresa.objects.create(
            nome='Loja', slug='loja', ativo=True, woo_webhook_secret='s',
        )

    def escrever(self, tmpdir, dados):
        import json
        caminho = tmpdir / 'respostas.json'
        caminho.write_text(json.dumps(dados), encoding='utf-8')
        return str(caminho)

    def test_importa_e_reimporta_sem_duplicar(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            arq = self.escrever(Path(d), [
                {'pergunta': 'Qual o prazo?', 'resposta': '5 dias úteis.'},
                {'pergunta': 'Tem frete grátis?', 'resposta': 'Acima de R$300.'},
                {'pergunta': '', 'resposta': 'sem titulo, ignora'},
            ])
            call_command('importar_respostas_rapidas', arquivo=arq, empresa='loja')
            self.assertEqual(RespostaRapida.objects.filter(empresa=self.empresa).count(), 2)

            # mesma exportação de novo: não duplica
            call_command('importar_respostas_rapidas', arquivo=arq, empresa='loja')
            self.assertEqual(RespostaRapida.objects.filter(empresa=self.empresa).count(), 2)

    def test_reimportar_atualiza_o_texto_alterado(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            arq = self.escrever(Path(d), [{'pergunta': 'Qual o prazo?', 'resposta': '5 dias.'}])
            call_command('importar_respostas_rapidas', arquivo=arq, empresa='loja')
            arq2 = self.escrever(Path(d), [{'pergunta': 'Qual o prazo?', 'resposta': '7 dias.'}])
            call_command('importar_respostas_rapidas', arquivo=arq2, empresa='loja')

            r = RespostaRapida.objects.get(empresa=self.empresa, titulo='Qual o prazo?')
            self.assertEqual(r.texto, '7 dias.')
            self.assertEqual(RespostaRapida.objects.filter(empresa=self.empresa).count(), 1)
