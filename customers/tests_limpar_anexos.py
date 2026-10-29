"""
Comando limpar_anexos_perigosos: a faxina do que entrou ANTES do bloqueio.

Este comando APAGA ARQUIVO EM PRODUÇÃO. O teste que mais importa aqui não é
o que ele pega — é o que ele NÃO pode pegar: .docx e .xlsx são arquivos ZIP
por dentro, e nota fiscal é o que o cliente manda o dia inteiro. Apagar por
engano é perda de dado irreversível.
"""
from io import StringIO

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase

from customers.models import MensagemWhatsApp
from customers.management.commands.limpar_anexos_perigosos import (
    _nome_original, _parece_nome_de_arquivo,
)
from tenants.models import Empresa

ZIP = b'PK\x03\x04' + b'\x00' * 40      # começo de docx/xlsx/zip
EXE = b'MZ\x90\x00' + b'\x00' * 40      # executável do Windows
JS = b'var _0x=function(){eval("")};'   # o trojan do incidente


class NomeOriginalTest(TestCase):
    def test_tira_todos_os_rotulos_que_o_sistema_grava(self):
        casos = {
            '[document] Proposta.js': 'Proposta.js',
            '[image] foto.jpg': 'foto.jpg',
            '[bloqueado:js] Proposta.js': 'Proposta.js',
            '[suspeito:qwerty] arquivo.qwerty': 'arquivo.qwerty',
            '[audio] ': '',
            '[image] *Atendente Yasmin* segue a foto': 'segue a foto',
            # Documento com legenda: "nome.ext — legenda"
            '[suspeito:p7s] NF 12345.p7s — pode faturar': 'NF 12345.p7s',
        }
        for bruto, esperado in casos.items():
            self.assertEqual(_nome_original(bruto), esperado, bruto)

    def test_so_trata_como_nome_de_arquivo_o_que_parece_nome(self):
        for texto in ('veja tudo em www.tarragona.com', 'baixei no pix.app',
                      'olha o pe da minha filha', 'chega dia 3.hoje nao'):
            self.assertFalse(_parece_nome_de_arquivo(texto), texto)
        for texto in ('Proposta.js', 'NF-12345.pdf', 'foto_do_pe.jpeg'):
            self.assertTrue(_parece_nome_de_arquivo(texto), texto)


class LimparAnexosTest(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(
            nome='Loja', slug='loja', ativo=True, woo_webhook_secret='s',
        )

    def criar(self, texto, conteudo, nome_disco):
        msg = MensagemWhatsApp.objects.create(
            empresa=self.empresa, tipo='resposta_cliente', canal='meta',
            status='recebido', destinatario_telefone='5516999990001',
            mensagem_texto=texto,
        )
        msg.midia_arquivo.save(nome_disco, ContentFile(conteudo), save=True)
        return msg

    def rodar(self, *args):
        out = StringIO()
        call_command('limpar_anexos_perigosos', *args, stdout=out)
        return out.getvalue()

    def test_acha_o_js_do_golpe_salvo_como_bin(self):
        """O caso real: o nome só existe no texto; no disco é '<id>.bin'."""
        msg = self.criar(
            '[document] PROPOSTA_COMERCIAL_ORCAMENTO_FINAL_2026-10-29.js',
            JS, 'golpe.bin',
        )
        saida = self.rodar()
        self.assertIn('ANEXOS PERIGOSOS GUARDADOS: 1', saida)
        self.assertIn(f'#{msg.id}', saida)
        self.assertIn('Nada foi movido', saida)
        msg.refresh_from_db()
        self.assertTrue(bool(msg.midia_arquivo))  # sem --apagar não mexe

    def test_apagar_move_pra_quarentena_e_mantem_o_historico(self):
        msg = self.criar('[document] virus.js', JS, 'golpe.bin')
        saida = self.rodar('--apagar')
        msg.refresh_from_db()
        self.assertFalse(bool(msg.midia_arquivo))
        self.assertTrue(msg.mensagem_texto.startswith('[bloqueado:js]'))
        self.assertIn('virus.js', msg.mensagem_texto)
        # Movido, não destruído: sem backup do volume, falso positivo que
        # escape da lista seria perda definitiva.
        self.assertIn('quarentena/', saida)

    # --- o caso que três revisores pegaram -------------------------------

    def test_nao_apaga_foto_por_causa_da_legenda(self):
        """A legenda é escrita pelo cliente e NÃO é nome de arquivo.
        'baixei no pix.app' termina em '.app', que está na lista negra."""
        legendas = [
            '[image] *Atendente Yasmin*\nveja tudo em www.tarragona.com',
            '[image] baixei no pix.app',
            '[image] mandei pelo zip.com do parceiro',
        ]
        for texto in legendas:
            self.criar(texto, b'\xff\xd8\xff\xe0' + b'\x00' * 20, 'foto.bin')
        saida = self.rodar('--apagar')
        self.assertIn('Nenhum anexo perigoso', saida)
        self.assertEqual(
            MensagemWhatsApp.objects.exclude(midia_arquivo='').count(), len(legendas)
        )

    def test_so_olha_o_que_o_cliente_mandou_por_padrao(self):
        enviada = MensagemWhatsApp.objects.create(
            empresa=self.empresa, tipo='atendimento_humano', canal='meta',
            status='enviado', destinatario_telefone='5516999990001',
            mensagem_texto='[document] catalogo.js',
        )
        enviada.midia_arquivo.save('env.bin', ContentFile(JS), save=True)
        self.assertNotIn('ANEXOS PERIGOSOS', self.rodar())
        self.assertIn('ANEXOS PERIGOSOS GUARDADOS: 1', self.rodar('--incluir-enviadas'))

    def test_id_escolhe_a_dedo(self):
        a = self.criar('[document] a.js', JS, 'a.bin')
        self.criar('[document] b.js', JS, 'b.bin')
        saida = self.rodar(f'--id={a.id}')
        self.assertIn('ANEXOS PERIGOSOS GUARDADOS: 1', saida)
        self.assertIn(f'#{a.id}', saida)

    def test_executavel_acusa_mesmo_com_nome_inocente(self):
        self.criar('[document] catalogo.pdf', EXE, 'x.bin')
        self.assertIn('ANEXOS PERIGOSOS GUARDADOS: 1', self.rodar())

    # --- o que ele NÃO pode destruir -------------------------------------

    def test_nao_apaga_nota_fiscal_em_docx(self):
        """docx é ZIP por dentro. Se a assinatura acusar sozinha, o comando
        apaga contrato e nota fiscal de verdade."""
        msg = self.criar('[document] Nota Fiscal 12345.docx', ZIP, 'nf.bin')
        saida = self.rodar('--apagar')
        self.assertIn('Nenhum anexo perigoso', saida)
        msg.refresh_from_db()
        self.assertTrue(bool(msg.midia_arquivo))

    def test_nao_apaga_planilha_nem_pdf_nem_foto(self):
        for texto, conteudo in [
            ('[document] pedido.xlsx', ZIP),
            ('[document] NFe3526011420.xml', b'<?xml version="1.0"?><nfe/>'),
            ('[image] defeito.jpg', b'\xff\xd8\xff\xe0' + b'\x00' * 20),
            ('[audio] ', b'OggS' + b'\x00' * 20),
        ]:
            self.criar(texto, conteudo, 'arq.bin')
        saida = self.rodar('--apagar')
        self.assertIn('Nenhum anexo perigoso', saida)
        self.assertEqual(
            MensagemWhatsApp.objects.exclude(midia_arquivo='').count(), 4
        )

    def test_zip_sem_nome_conhecido_acusa(self):
        """Mesmo ZIP, mas sem nome que o explique: aí sim é suspeito."""
        self.criar('[document] arquivo', ZIP, 'x.bin')
        self.assertIn('ANEXOS PERIGOSOS GUARDADOS: 1', self.rodar())

    def test_filtro_por_empresa(self):
        outra = Empresa.objects.create(
            nome='Outra', slug='outra', ativo=True, woo_webhook_secret='s',
        )
        self.criar('[document] virus.js', JS, 'a.bin')
        m2 = MensagemWhatsApp.objects.create(
            empresa=outra, tipo='resposta_cliente', canal='meta',
            status='recebido', destinatario_telefone='5516999990002',
            mensagem_texto='[document] outro.js',
        )
        m2.midia_arquivo.save('b.bin', ContentFile(JS), save=True)
        saida = self.rodar('--empresa=loja')
        self.assertIn('ANEXOS PERIGOSOS GUARDADOS: 1', saida)
