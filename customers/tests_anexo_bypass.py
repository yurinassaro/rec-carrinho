"""
Testes dos furos achados na auditoria de 29/10/2026, depois do golpe do .js:

1. ponto no fim do nome ("fatura.js.") driblava a checagem de extensão;
2. extensão dupla ("orcamento.js.pdf") passava;
3. faltavam os vetores de maior volume hoje (html, svg, Office com macro);
4. o backstop por MIME era cego pra zip/rar;
5. tipo desconhecido entrava como link normal, sem nenhum aviso.

E as regressões que NÃO podem acontecer: NF-e em XML, nome com domínio no
meio ("notafiscal.com.br.pdf") e o MIME coringa não podem virar bloqueio.
"""
from django.test import SimpleTestCase

from customers import webhooks_meta
from customers.webhooks_meta import anexo_desconhecido, anexo_perigoso


class PontoNoFimTest(SimpleTestCase):
    """O Windows ignora ponto e espaço no fim: 'fatura.js.' abre como .js."""

    def test_ponto_no_fim_nao_dribla(self):
        for nome in ('PROPOSTA.js.', 'PROPOSTA.js..', 'PROPOSTA.js. ', 'PROPOSTA.js.\t'):
            perigoso, rotulo = anexo_perigoso(nome, 'application/octet-stream')
            self.assertTrue(perigoso, f'{nome!r} deveria bloquear')
            self.assertEqual(rotulo, 'js', nome)

    def test_espaco_invisivel_no_fim_nao_dribla(self):
        perigoso, _ = anexo_perigoso('PROPOSTA.exe​', 'application/octet-stream')
        self.assertTrue(perigoso)


class ExtensaoDuplaTest(SimpleTestCase):

    def test_extensao_dupla_bloqueia(self):
        for nome in ('orcamento.js.pdf', 'nota.exe.png', 'planilha.vbs.xlsx'):
            self.assertTrue(anexo_perigoso(nome, 'application/pdf')[0], nome)

    def test_dominio_no_meio_do_nome_continua_passando(self):
        """'com' e 'app' estão na lista de perigosas, mas aparecem em nome
        legítimo. Checar todas as partes contra a lista toda quebraria isto."""
        for nome in ('notafiscal.com.br.pdf', 'tarragona.com.br.pdf',
                     'recibo.app.pdf', 'catalogo.verao.2026.pdf'):
            self.assertFalse(anexo_perigoso(nome, 'application/pdf')[0], nome)


class CaractereInvisivelTest(SimpleTestCase):
    """Caractere invisível grudado na extensão não muda o que o sistema
    operacional executa, mas driblava a comparação com a lista — o bloqueio
    vermelho virava aviso amarelo COM botão de baixar."""

    def test_invisivel_depois_da_extensao_nao_dribla(self):
        for sufixo in ('‮', '⁣', '‍', '﻿', ' '):
            nome = f'PROPOSTA.js{sufixo}'
            self.assertTrue(anexo_perigoso(nome, 'application/octet-stream')[0],
                            f'{nome!r} deveria bloquear')

    def test_fullwidth_normaliza(self):
        self.assertTrue(anexo_perigoso('PROPOSTA.ｊｓ', '')[0])


class AvisoEmVezDeBloqueioTest(SimpleTestCase):
    """html, svg e Office com macro são arma de golpe E arquivo de trabalho.
    Bloquear é irreversível (a mídia expira na Meta), então vão pro amarelo."""

    AMARELOS = [
        ('comprovante.html', 'text/html'),
        ('extrato.htm', 'text/html'),
        ('arte_fornecedor.svg', 'image/svg+xml'),
        ('tabela de precos 2026.xlsm', ''),
        ('pedido.xlsb', ''),
        ('orcamento.docm', ''),
    ]

    def test_nao_bloqueia(self):
        for nome, mime in self.AMARELOS:
            self.assertFalse(anexo_perigoso(nome, mime)[0], f'{nome} nao devia bloquear')

    def test_mas_avisa(self):
        for nome, mime in self.AMARELOS:
            self.assertTrue(anexo_desconhecido(nome, mime)[0], f'{nome} devia avisar')


class VetoresNovosTest(SimpleTestCase):

    def test_xll_iqy_slk_bloqueiam(self):
        """Estes não têm uso legítimo em loja: xll é DLL do Excel, iqy e slk
        puxam payload remoto sem nem precisar de macro."""
        for nome in ('addin.xll', 'consulta.iqy', 'planilha.slk'):
            self.assertTrue(anexo_perigoso(nome, '')[0], nome)

    def test_atalhos_do_windows_bloqueiam(self):
        for nome in ('pagamento.url', 'pasta.scf', 'ajuda.chm', 'config.msc'):
            self.assertTrue(anexo_perigoso(nome, '')[0], nome)

    def test_sh_e_dll_fecham_a_simetria_com_o_mime(self):
        for nome in ('script.sh', 'lib.dll'):
            self.assertTrue(anexo_perigoso(nome, '')[0], nome)


class BackstopDeContainerTest(SimpleTestCase):
    """O backstop do download só olha o MIME. Antes não tinha container nenhum."""

    def test_mime_de_container_esta_na_lista(self):
        for m in ('application/zip', 'application/x-rar-compressed',
                  'application/x-7z-compressed', 'application/gzip'):
            self.assertIn(m, webhooks_meta.MIME_PERIGOSOS, m)

    def test_bloqueia_por_mime_mesmo_sem_nome(self):
        self.assertTrue(anexo_perigoso('', 'application/zip')[0])


class NaoPodeBloquearTest(SimpleTestCase):
    """Falso positivo aqui é prejuízo: cliente não consegue mandar documento."""

    def test_nfe_em_xml_passa(self):
        """NF-e brasileira chega como XML. Bloquear isso quebra a operação."""
        self.assertFalse(anexo_perigoso('NFe35260114200166000187.xml', 'text/xml')[0])
        self.assertFalse(anexo_desconhecido('NFe35260114200166000187.xml', 'text/xml')[0])

    def test_documentos_do_dia_a_dia_passam(self):
        casos = [
            ('nota_fiscal.pdf', 'application/pdf'),
            ('comprovante.jpg', 'image/jpeg'),
            ('defeito.png', 'image/png'),
            ('audio.ogg', 'audio/ogg'),
            ('planilha.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('contrato.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
            ('contato.vcf', 'text/vcard'),
        ]
        for nome, mime in casos:
            self.assertFalse(anexo_perigoso(nome, mime)[0], f'{nome} bloqueou')
            self.assertFalse(anexo_desconhecido(nome, mime)[0], f'{nome} virou suspeito')

    def test_extensao_esperada_vence_mime_errado(self):
        """Celular Android reporta docx/xlsx como application/zip. Bloquear
        por isso perderia a nota fiscal do cliente pra sempre — a mídia
        expira na Meta e não há como pedir de novo."""
        for nome in ('pedido.xlsx', 'contrato.docx', 'nota.pdf', 'recibo.odt'):
            self.assertFalse(anexo_perigoso(nome, 'application/zip')[0], nome)

    def test_mas_zip_de_verdade_continua_bloqueando(self):
        self.assertTrue(anexo_perigoso('arquivo.zip', 'application/zip')[0])
        self.assertTrue(anexo_perigoso('', 'application/zip')[0])

    def test_foto_sem_extensao_nao_vira_suspeita(self):
        """MIME_ESPERADOS só tinha documento: foto mandada como documento com
        nome sem extensão ganhava aviso amarelo à toa."""
        for nome, mime in [('foto', 'image/jpeg'), ('audio do cliente', 'audio/ogg'),
                           ('video', 'video/mp4')]:
            self.assertFalse(anexo_desconhecido(nome, mime)[0], f'{nome} virou suspeito')

    def test_arquivos_de_negocio_brasileiros_passam(self):
        for nome in ('NF 12345.p7s', 'pedido.eml', 'arte.cdr', 'proposta.pages',
                     'foto.jfif'):
            self.assertFalse(anexo_perigoso(nome, '')[0], f'{nome} bloqueou')
            self.assertFalse(anexo_desconhecido(nome, '')[0], f'{nome} virou suspeito')

    def test_mime_coringa_nao_bloqueia(self):
        """application/octet-stream é o MIME que o WhatsApp manda em documento
        legítimo. Se virar bloqueio, derruba anexo de verdade em massa."""
        self.assertNotIn('application/octet-stream', webhooks_meta.MIME_PERIGOSOS)
        self.assertFalse(anexo_perigoso('contrato.pdf', 'application/octet-stream')[0])


class TipoDesconhecidoTest(SimpleTestCase):

    def test_extensao_estranha_vira_suspeita(self):
        estranho, ext = anexo_desconhecido('arquivo.qwerty', 'application/octet-stream')
        self.assertTrue(estranho)
        self.assertEqual(ext, 'qwerty')

    def test_sem_extensao_com_mime_coringa_vira_suspeito(self):
        estranho, ext = anexo_desconhecido('arquivo', 'application/octet-stream')
        self.assertTrue(estranho)
        self.assertEqual(ext, '')

    def test_o_que_e_esperado_nao_vira_suspeito(self):
        self.assertFalse(anexo_desconhecido('nota.pdf', 'application/octet-stream')[0])


class SimetriaDasListasTest(SimpleTestCase):
    """Pra cada MIME perigoso, a extensão canônica tem que estar bloqueada
    também — senão o atacante escolhe por qual dos dois lados entrar."""

    PARES = {
        'text/javascript': 'js',
        'application/x-sh': 'sh',
        'application/x-msdownload': 'dll',
        'application/java-archive': 'jar',
        'application/vnd.android.package-archive': 'apk',
        'application/x-ms-shortcut': 'lnk',
        'application/zip': 'zip',
    }

    def test_html_e_svg_sairam_das_duas_listas_juntos(self):
        """Se o MIME ficasse em MIME_PERIGOSOS depois de a extensão virar
        aviso, o arquivo seria bloqueado assim mesmo pelo outro lado."""
        for m in ('text/html', 'image/svg+xml'):
            self.assertNotIn(m, webhooks_meta.MIME_PERIGOSOS, m)
            self.assertIn(m, webhooks_meta.MIME_AVISO, m)
        for e in ('html', 'svg', 'xlsm'):
            self.assertNotIn(e, webhooks_meta.EXT_PERIGOSAS, e)
            self.assertIn(e, webhooks_meta.EXT_AVISO, e)

    def test_todo_mime_tem_a_extensao_correspondente(self):
        todas = webhooks_meta.EXT_PERIGOSAS | webhooks_meta.EXT_CONTAINER
        for mime, ext in self.PARES.items():
            self.assertIn(mime, webhooks_meta.MIME_PERIGOSOS, mime)
            self.assertIn(ext, todas, f'{mime} existe mas .{ext} não bloqueia')
