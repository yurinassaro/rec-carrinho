"""
Testes do bloqueio de anexo perigoso no inbox.

O que precisa estar protegido: documento de tipo usado em golpe (.js, .bat,
.exe, .zip com payload…) chegando pelo webhook da Meta NÃO pode ser baixado
pro servidor nem virar link clicável pro atendente. Ele entra marcado
`[bloqueado:...]` pra o inbox exibir só o aviso. Arquivo legítimo (pdf, docx,
imagem, áudio) continua passando normalmente.
"""
from unittest.mock import patch

from django.test import TestCase

from customers.models import MensagemWhatsApp
from customers import webhooks_meta
from tenants.models import Empresa


class AnexoPerigosoClassificacaoTest(TestCase):
    """A regra pura de classificação, sem webhook."""

    def test_js_do_golpe_bloqueia(self):
        nome = 'PROPOSTA_COMERCIAL_ORÇAMENTO_FINAL_2026-10-29_19745632147527.js'
        perigoso, rotulo = webhooks_meta.anexo_perigoso(nome, 'text/javascript')
        self.assertTrue(perigoso)
        self.assertEqual(rotulo, 'js')

    def test_dupla_extensao_bloqueia(self):
        # Truque clássico: parece PDF, é JS.
        perigoso, _ = webhooks_meta.anexo_perigoso('orcamento.PDF.js', '')
        self.assertTrue(perigoso)

    def test_containers_bloqueiam(self):
        for nome in ('fatura.zip', 'boleto.rar', 'docs.7z'):
            self.assertTrue(webhooks_meta.anexo_perigoso(nome, '')[0], nome)

    def test_executaveis_e_atalhos_bloqueiam(self):
        for nome in ('contrato.exe', 'nota.bat', 'link.lnk', 'setup.msi', 'app.apk'):
            self.assertTrue(webhooks_meta.anexo_perigoso(nome, '')[0], nome)

    def test_mime_perigoso_sem_extensao_bloqueia(self):
        perigoso, _ = webhooks_meta.anexo_perigoso('arquivo', 'application/javascript')
        self.assertTrue(perigoso)

    def test_legitimos_passam(self):
        legit = [
            ('Proposta_Comercial.pdf', 'application/pdf'),
            ('planilha.xlsx', ''),
            ('contrato.docx', ''),
            ('foto.jpg', 'image/jpeg'),
            ('audio.ogg', 'audio/ogg'),
            ('video.mp4', 'video/mp4'),
        ]
        for nome, mime in legit:
            self.assertFalse(webhooks_meta.anexo_perigoso(nome, mime)[0], nome)


class AnexoPerigosoWebhookTest(TestCase):
    """O fluxo do webhook: recebe documento, decide baixar ou bloquear."""

    def setUp(self):
        self.empresa = Empresa.objects.create(
            nome='Loja', slug='loja', ativo=True, woo_webhook_secret='s',
            meta_access_token='tok', meta_resposta_automatica='',
        )

    def _doc(self, filename, mime='application/octet-stream'):
        return {
            'from': '5511999999999',
            'id': 'wamid.TEST',
            'timestamp': '1730200000',
            'type': 'document',
            'document': {'id': 'MID123', 'filename': filename, 'mime_type': mime},
        }

    @patch.object(webhooks_meta, '_encaminhar_para_humano')
    @patch.object(webhooks_meta, '_salvar_midia_recebida')
    def test_documento_perigoso_nao_baixa_e_marca(self, mock_salvar, _mock_enc):
        msg = self._doc('PROPOSTA_ORCAMENTO_FINAL_19745632147527.js', 'text/javascript')
        webhooks_meta._process_incoming_message(msg, [], self.empresa)

        # Não tentou baixar a mídia perigosa.
        mock_salvar.assert_not_called()

        reg = MensagemWhatsApp.objects.get(meta_message_id='wamid.TEST')
        self.assertTrue(reg.mensagem_texto.startswith('[bloqueado:js]'))
        self.assertIn('19745632147527.js', reg.mensagem_texto)
        self.assertFalse(bool(reg.midia_arquivo))

    @patch.object(webhooks_meta, '_encaminhar_para_humano')
    @patch.object(webhooks_meta, '_salvar_midia_recebida')
    def test_documento_legitimo_baixa_normal(self, mock_salvar, _mock_enc):
        msg = self._doc('Proposta_Comercial.pdf', 'application/pdf')
        webhooks_meta._process_incoming_message(msg, [], self.empresa)

        # PDF legítimo: segue o fluxo de download.
        mock_salvar.assert_called_once()

        reg = MensagemWhatsApp.objects.get(meta_message_id='wamid.TEST')
        self.assertTrue(reg.mensagem_texto.startswith('[document]'))
        self.assertNotIn('[bloqueado', reg.mensagem_texto)
