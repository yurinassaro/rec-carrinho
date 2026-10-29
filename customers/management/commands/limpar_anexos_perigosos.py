"""
Varre a mídia já guardada no servidor atrás de anexo perigoso que entrou ANTES
do bloqueio automático (commit 6d31788) e, se mandarem, apaga o arquivo do disco.

O bloqueio novo só vale pro que chega de agora em diante. Este comando é a
faxina do que já estava lá — o caso real foi um .js de trojan que chegou
disfarçado de "proposta comercial" e virou link clicável no inbox.

Por padrão SÓ MOSTRA. Para apagar de verdade é preciso --apagar.

    # ver o que tem (não mexe em nada)
    python manage.py limpar_anexos_perigosos

    # apagar os arquivos perigosos do disco
    python manage.py limpar_anexos_perigosos --apagar

    # só de uma empresa
    python manage.py limpar_anexos_perigosos --empresa=tarragona
"""
import re

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from customers.models import MensagemWhatsApp
from customers.webhooks_meta import (
    EXT_ESPERADAS, _extensao_arquivo, anexo_perigoso,
)

# O texto da mensagem guarda o nome original assim: "[document] Proposta.js".
# O arquivo no disco se chama "<id>.bin", então o nome de verdade só está aqui.
# Tem que casar com TODO rótulo que o sistema grava — inclusive os de mídia
# enviada pelo próprio atendente e a assinatura "*Atendente Fulano*".
RE_ROTULO = re.compile(
    r'^\[(?:document|image|audio|video|sticker|voice|unsupported|sem suporte'
    r'|bloqueado:[^\]]*|suspeito:[^\]]*)\]\s*'
)
RE_ASSINATURA = re.compile(r'^\*Atendente [^*]{0,60}\*\s*')

# Pra onde o arquivo suspeito vai. Fora de inbox_midia/, que o nginx bloqueia
# e a view do inbox serve — então a quarentena não fica acessível por link.
QUARENTENA = 'quarentena/'

# Assinaturas que NUNCA são de arquivo legítimo de cliente de loja. Estas
# acusam sozinhas, mesmo que o nome pareça inocente.
ASSINATURAS_CERTAS = [
    (b'MZ', 'executável do Windows (.exe/.dll)'),
    (b'\x7fELF', 'executável do Linux'),
    (b'\xca\xfe\xba\xbe', 'executável Java/Mach-O'),
    (b'#!', 'script com shebang'),
]
# Estas são AMBÍGUAS e não podem acusar sozinhas: .docx, .xlsx e .pptx são
# arquivos ZIP por dentro (começam com PK), e .doc/.xls antigos são OLE.
# Apagar por causa delas destruiria nota fiscal e contrato de verdade.
ASSINATURAS_AMBIGUAS = [
    (b'PK\x03\x04', 'compactado (zip — mas docx/xlsx também são)'),
    (b'Rar!', 'compactado (rar)'),
    (b'7z\xbc\xaf\x27\x1c', 'compactado (7z)'),
    (b'\xd0\xcf\x11\xe0', 'Office antigo OLE (pode ter macro)'),
]


def _nome_original(texto):
    """Tira o rótulo (e a assinatura do atendente, quando for mídia que a
    loja mandou) e devolve o nome do arquivo como o cliente mandou."""
    t = RE_ROTULO.sub('', texto or '').strip()
    t = RE_ASSINATURA.sub('', t).strip()
    # Documento com legenda é gravado como "nome.ext — legenda do cliente".
    return t.split(' — ', 1)[0].strip()


# Nome de arquivo é um token só, sem espaço, terminando em extensão curta.
RE_PARECE_NOME = re.compile(r'^[^\s/\\]{1,180}\.[A-Za-z0-9-]{1,12}$')


def _parece_nome_de_arquivo(t):
    """
    O texto da mensagem guarda o NOME quando é documento, mas guarda a
    LEGENDA quando é foto/áudio. Rodar a lista negra em cima de legenda é
    como esta ferramenta apagaria foto de cliente: "baixei no pix.app"
    termina em ".app", que está na lista de extensões perigosas.
    """
    return bool(RE_PARECE_NOME.match(t or ''))


def _assinatura(msg, nome):
    """
    Lê os primeiros bytes do arquivo salvo e diz se eles acusam.

    A assinatura ambígua (PK, OLE) só conta quando o NOME não a explica:
    "contrato.docx" começando com PK é um docx normal; um arquivo sem nome
    conhecido começando com PK é um zip que alguém disfarçou.
    """
    try:
        with msg.midia_arquivo.open('rb') as f:
            cabeca = f.read(8)
    except Exception as e:
        return '', f'(não consegui ler: {e})'
    for prefixo, rotulo in ASSINATURAS_CERTAS:
        if cabeca.startswith(prefixo):
            return rotulo, ''
    ext = _extensao_arquivo(nome)
    if ext in EXT_ESPERADAS:
        return '', ''  # o nome explica os bytes — é documento de verdade
    for prefixo, rotulo in ASSINATURAS_AMBIGUAS:
        if cabeca.startswith(prefixo):
            return rotulo, ''
    return '', ''


class Command(BaseCommand):
    help = 'Lista (e opcionalmente apaga) anexos perigosos que já estavam guardados'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apagar', action='store_true',
            help='Apaga de verdade o arquivo do disco. Sem isso, só mostra.',
        )
        parser.add_argument(
            '--empresa', default='',
            help='Slug da empresa. Vazio = todas.',
        )
        parser.add_argument(
            '--id', type=int, action='append', default=[],
            help='Mexe só nestas mensagens (pode repetir). Sem isso, em todas as encontradas.',
        )
        parser.add_argument(
            '--incluir-enviadas', action='store_true',
            help='Inclui também a mídia que a própria loja mandou. O golpe vem '
                 'do cliente, então o padrão é olhar só o que foi recebido.',
        )

    def handle(self, *args, **opts):
        qs = MensagemWhatsApp.objects.exclude(
            midia_arquivo='',
        ).exclude(midia_arquivo=None).select_related('empresa')
        if opts['empresa']:
            qs = qs.filter(empresa__slug=opts['empresa'])
        if not opts['incluir_enviadas']:
            qs = qs.filter(tipo='resposta_cliente')
        if opts['id']:
            qs = qs.filter(id__in=opts['id'])

        total = qs.count()
        self.stdout.write(f'Mensagens com arquivo guardado: {total}')
        if not total:
            return

        suspeitas = []
        for msg in qs.order_by('-id').iterator():
            nome = _nome_original(msg.mensagem_texto)
            # A lista negra é um classificador de NOME DE ARQUIVO. Só pode
            # rodar sobre algo que de fato seja um nome de arquivo.
            perigoso, ext = (False, '')
            if _parece_nome_de_arquivo(nome):
                perigoso, ext = anexo_perigoso(nome, '')
            assinatura, erro_leitura = _assinatura(msg, nome)
            if not (perigoso or assinatura):
                continue
            suspeitas.append((msg, nome, ext, assinatura, erro_leitura))

        if not suspeitas:
            self.stdout.write(self.style.SUCCESS(
                'Nenhum anexo perigoso guardado. Nada a fazer.'
            ))
            return

        self.stdout.write('')
        self.stdout.write(self.style.WARNING(
            f'ANEXOS PERIGOSOS GUARDADOS: {len(suspeitas)}'
        ))
        self.stdout.write('-' * 100)
        for msg, nome, ext, assinatura, erro in suspeitas:
            quando = msg.created_at.strftime('%d/%m/%Y %H:%M') if msg.created_at else '?'
            motivo = f'extensão .{ext}' if ext else ''
            if assinatura:
                motivo = f'{motivo} + {assinatura}'.strip(' +')
            self.stdout.write(
                f'  #{msg.id} | {msg.empresa.slug} | {quando} | '
                f'{msg.destinatario_telefone}\n'
                f'      nome: {nome or "(sem nome)"}\n'
                f'      motivo: {motivo or "(só a assinatura)"} {erro}\n'
                f'      disco: {msg.midia_arquivo.name}\n'
                f'      link no inbox: /crm/inbox/midia/{msg.id}/'
            )
        self.stdout.write('-' * 100)

        if not opts['apagar']:
            self.stdout.write('')
            self.stdout.write(
                'Nada foi movido. Confira a lista acima e, se estiver certa, '
                'rode de novo com --apagar (ou com --id para escolher a dedo).'
            )
            return

        movidos, falhas = 0, 0
        for msg, nome, ext, assinatura, _erro in suspeitas:
            origem = msg.midia_arquivo.name
            try:
                # Mover, não destruir. O servidor não é repo git e o volume de
                # mídia não tem backup — se um falso positivo escapar da lista,
                # apagar aqui é perda definitiva. O arquivo some do inbox na
                # mesma hora (o nome no banco muda), e a faxina do disco fica
                # pra depois, com calma.
                destino = f'{QUARENTENA}{msg.id}-{origem.rsplit("/", 1)[-1]}'
                with msg.midia_arquivo.open('rb') as f:
                    conteudo = f.read()
                default_storage.save(destino, ContentFile(conteudo))
                msg.midia_arquivo.delete(save=False)
                # O histórico continua: o atendente vê que chegou e que foi
                # bloqueado, só não tem mais o arquivo pra clicar.
                msg.mensagem_texto = f'[bloqueado:{ext or "arquivo"}] {nome}'.strip()
                msg.midia_arquivo = None
                msg.save(update_fields=['mensagem_texto', 'midia_arquivo'])
                movidos += 1
                self.stdout.write(self.style.SUCCESS(
                    f'  #{msg.id}: {origem} -> {destino}'
                ))
            except Exception as e:
                falhas += 1
                self.stdout.write(self.style.ERROR(f'  FALHOU #{msg.id}: {e}'))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Arquivos tirados do inbox: {movidos} (em media/{QUARENTENA})'
        ))
        self.stdout.write(
            'Eles NÃO estão mais acessíveis pelo inbox. Confira a quarentena e, '
            'quando tiver certeza, apague a pasta no servidor.'
        )
        if falhas:
            self.stdout.write(self.style.ERROR(f'Falhas: {falhas}'))
