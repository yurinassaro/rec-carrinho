"""
Webhook da Meta WhatsApp Cloud API.
Recebe eventos de mensagens recebidas, status de entrega, leitura, etc.

Configurar no Meta Business:
  Meta Business > WhatsApp > Configuracao > Webhooks
  - Callback URL: https://SEU-DOMINIO/webhooks/meta/
  - Verify Token: (mesmo valor de empresa.meta_webhook_verify_token)
  - Campos: messages, message_deliveries, message_reads
"""
import json
import logging
import re
import unicodedata

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

from tenants.models import Empresa
from customers.models import MensagemWhatsApp, Customer

logger = logging.getLogger(__name__)


@csrf_exempt
def meta_webhook(request):
    """
    Endpoint unico para Meta WhatsApp webhook.
    GET = verificacao (challenge)
    POST = eventos (mensagens recebidas, status updates)
    """
    if request.method == 'GET':
        return _verify_webhook(request)
    elif request.method == 'POST':
        return _process_webhook(request)
    return HttpResponse(status=405)


def _verify_webhook(request):
    """
    Meta envia GET com hub.mode, hub.verify_token e hub.challenge.
    Retornamos hub.challenge se o token bater.
    """
    mode = request.GET.get('hub.mode')
    token = request.GET.get('hub.verify_token')
    challenge = request.GET.get('hub.challenge')

    if mode != 'subscribe' or not token or not challenge:
        logger.warning('Meta webhook verify: parametros incompletos')
        return HttpResponse('Bad request', status=400)

    # Verificar token em qualquer empresa ativa
    empresa = Empresa.objects.filter(
        ativo=True,
        meta_webhook_verify_token=token,
    ).first()

    if empresa:
        logger.info(f'Meta webhook verificado para {empresa.slug}')
        return HttpResponse(challenge, content_type='text/plain')

    logger.warning(f'Meta webhook verify: token invalido ({token})')
    return HttpResponse('Forbidden', status=403)


def _process_webhook(request):
    """
    Processa eventos POST da Meta.
    Estrutura: { object: "whatsapp_business_account", entry: [...] }
    """
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'invalid json'}, status=400)

    if payload.get('object') != 'whatsapp_business_account':
        return HttpResponse('ok')

    for entry in payload.get('entry', []):
        for change in entry.get('changes', []):
            value = change.get('value', {})
            metadata = value.get('metadata', {})
            phone_number_id = metadata.get('phone_number_id', '')

            # Identificar empresa pelo phone_number_id
            empresa = Empresa.objects.filter(
                ativo=True,
                meta_phone_number_id=phone_number_id,
            ).first()

            if not empresa:
                logger.warning(
                    f'Meta webhook: phone_number_id {phone_number_id} '
                    f'nao encontrado em nenhuma empresa'
                )
                continue

            # Processar status updates (entregue, lido)
            for status in value.get('statuses', []):
                _process_status_update(status, empresa)

            # Processar mensagens recebidas (respostas dos clientes)
            for message in value.get('messages', []):
                contacts = value.get('contacts', [])
                _process_incoming_message(message, contacts, empresa)

    return HttpResponse('ok')


def _process_status_update(status_data, empresa):
    """
    Atualiza status de mensagem enviada: sent, delivered, read, failed.
    """
    wamid = status_data.get('id', '')
    status = status_data.get('status', '')
    timestamp = status_data.get('timestamp', '')

    if not wamid:
        return

    # Buscar mensagem original pelo meta_message_id
    msg = MensagemWhatsApp.objects.filter(
        empresa=empresa,
        meta_message_id=wamid,
    ).first()

    if not msg:
        return

    ts = timezone.datetime.fromtimestamp(
        int(timestamp), tz=timezone.utc
    ) if timestamp else timezone.now()

    if status == 'delivered':
        msg.status = 'entregue'
        msg.entregue_em = ts
        msg.save(update_fields=['status', 'entregue_em'])
        logger.info(f'Mensagem {wamid} entregue')

    elif status == 'read':
        msg.status = 'lido'
        msg.lido_em = ts
        msg.save(update_fields=['status', 'lido_em'])
        logger.info(f'Mensagem {wamid} lida')

    elif status == 'failed':
        errors = status_data.get('errors', [])
        error_msg = errors[0].get('message', '') if errors else ''
        msg.status = 'falha'
        msg.error_message = error_msg
        msg.save(update_fields=['status', 'error_message'])
        logger.error(f'Mensagem {wamid} falhou: {error_msg}')


MIDIA_EXT = {
    'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp',
    'audio/ogg': 'ogg', 'audio/mpeg': 'mp3', 'audio/mp4': 'm4a', 'audio/aac': 'aac',
    'audio/amr': 'amr', 'video/mp4': 'mp4', 'video/3gpp': '3gp', 'application/pdf': 'pdf',
}
MIDIA_MAX_BYTES = 25 * 1024 * 1024

# Extensão de verdade só tem letra, número e hífen. Serve pra jogar fora o
# caractere invisível que o atacante gruda no fim pra driblar a lista.
RE_SO_EXTENSAO = re.compile(r'[^a-z0-9-]')

# Extensões usadas por malware que se disfarça de "orçamento/proposta" no
# WhatsApp (o clássico golpe do arquivo .js). Documento com uma dessas é
# bloqueado: não baixamos pro servidor e o inbox mostra aviso em vez de link.
EXT_PERIGOSAS = {
    'js', 'jse', 'mjs', 'vbs', 'vbe', 'wsf', 'wsh', 'hta', 'bat', 'cmd',
    'com', 'exe', 'scr', 'pif', 'cpl', 'lnk', 'ps1', 'psm1', 'msi', 'msp',
    'reg', 'jar', 'apk', 'app', 'dmg', 'iso', 'img', 'vhd',
    # xll é DLL carregada pelo Excel; iqy e slk puxam payload remoto sozinhos.
    # Nenhum dos três tem uso legítimo numa loja.
    'xll', 'iqy', 'slk',
    # Arquivos de texto que o Windows trata como ação ao abrir/visualizar.
    'url', 'scf', 'inf', 'chm', 'msc', 'hlp', 'jnlp', 'sct', 'wsc', 'ws',
    'vb', 'shb', 'shs', 'ins', 'isp', 'mst', 'gadget', 'appref-ms',
    'settingcontent-ms', 'library-ms', 'diagcab',
    # OneNote virou vetor comum.
    'one', 'onepkg',
    # Resto da família PowerShell e instaladores modernos.
    'ps1xml', 'psc1', 'psd1', 'msix', 'msixbundle', 'appx', 'appxbundle',
    # Fechando a simetria com MIME_PERIGOSOS (x-sh/x-csh/x-msdownload).
    'sh', 'csh', 'bash', 'dll',
}

# NÃO bloqueadas — avisadas (tarja amarela, baixa só por download).
#
# São arma de golpe de verdade (HTML de phishing é hoje o anexo malicioso mais
# comum; SVG executa script; Office com macro roda ao abrir). Mas também são
# arquivo de trabalho legítimo: fornecedor manda planilha com macro, banco
# gera comprovante em HTML, fornecedor manda arte em SVG. E bloquear aqui é
# IRREVERSÍVEL — a mídia expira na Meta e não há como pedir de novo.
#
# O que tira o veneno delas: inbox_midia agora serve com
# Content-Disposition: attachment e nosniff, então nenhuma delas executa no
# nosso domínio com a sessão do atendente. Sobra o risco de o atendente abrir
# no computador dele — e para isso o aviso amarelo é a resposta certa.
EXT_AVISO = {
    'html', 'htm', 'xhtml', 'shtml', 'mhtml', 'mht',
    'svg', 'svgz',
    'docm', 'dotm', 'xlsm', 'xlsb', 'xlam', 'xla', 'pptm', 'potm',
    'ppam', 'ppsm',
}
MIME_AVISO = {
    'text/html', 'application/xhtml+xml', 'image/svg+xml',
    'application/vnd.ms-excel.sheet.macroenabled.12',
    'application/vnd.ms-word.document.macroenabled.12',
    'application/vnd.ms-powerpoint.presentation.macroenabled.12',
    'application/vnd.ms-excel.addin.macroenabled.12',
    'application/vnd.ms-excel.sheet.binary.macroenabled.12',
}

# As que NUNCA aparecem no meio de um nome legítimo. Só estas são checadas nas
# partes do meio ("orcamento.js.pdf"). Não dá pra checar o nome inteiro contra
# a lista toda: 'com' está lá, e "notafiscal.com.br.pdf" é nome legítimo.
EXT_INEQUIVOCAS = {
    'js', 'jse', 'mjs', 'vbs', 'vbe', 'wsf', 'hta', 'bat', 'cmd', 'exe',
    'scr', 'pif', 'cpl', 'lnk', 'ps1', 'msi', 'jar', 'apk', 'dll',
    'docm', 'dotm', 'xlsm', 'xlsb', 'xll', 'pptm', 'scf', 'chm', 'msc',
}
# Containers que escondem o payload (o arquivo real só aparece ao extrair) —
# também bloqueados, porque é como o .js costuma chegar "empacotado".
EXT_CONTAINER = {
    'zip', 'rar', '7z', 'gz', 'tgz', 'bz2', 'cab', 'arj', 'ace', 'z',
    'xz', 'lzh', 'lha', 'tar', 'iso', 'vhdx', 'wim', 'zipx',
}

# Reforço por MIME, caso o nome venha sem extensão confiável.
MIME_PERIGOSOS = {
    'text/javascript', 'application/javascript', 'application/x-javascript',
    'application/ecmascript', 'application/x-msdownload',
    'application/x-msdos-program', 'application/x-executable',
    'application/vnd.microsoft.portable-executable', 'application/x-sh',
    'application/x-bat', 'application/bat', 'application/x-csh',
    'application/java-archive', 'application/vnd.android.package-archive',
    'application/x-apple-diskimage', 'application/x-ms-shortcut',
    # Containers: o backstop do download era cego pra eles.
    'application/zip', 'application/x-zip-compressed', 'application/x-rar-compressed',
    'application/vnd.rar', 'application/x-7z-compressed', 'application/gzip',
    'application/x-gzip', 'application/x-tar', 'application/x-bzip2',
    'application/x-iso9660-image', 'application/vnd.ms-cab-compressed',
    # Resto da simetria com EXT_PERIGOSAS.
    'application/x-msi', 'application/x-powershell', 'application/hta',
    'application/x-vbs', 'application/x-ms-installer',
}

# DELIBERADAMENTE DE FORA — não "complete" a lista com estes:
#   application/octet-stream → é o MIME coringa que o WhatsApp manda em
#     documento legítimo. Bloquear por ele derruba anexo de verdade em massa.
#     O caso dele é o aviso amarelo de "tipo não identificado", não o bloqueio.
#   xml / text/xml → NF-e brasileira chega legitimamente como XML.
#   pdf, docx, xlsx, pptx, odt, ods, csv, doc, xls e imagem/áudio/vídeo →
#     é o que o cliente de uma loja manda o dia inteiro.


def _partes_nome(nome):
    """
    Quebra o nome do arquivo em extensões, da última pra primeira.

    Normaliza antes porque o nome é o campo que o atacante controla:
      - o Windows ignora ponto e espaço no fim ("fatura.js." abre como .js);
      - caractere invisível ou de direção ("fatura.js‮") não muda o que o
        sistema operacional executa, mas driblava a comparação com a lista.
    Por isso a extensão é reduzida a letras, números e hífen antes de comparar.
    """
    nome = unicodedata.normalize('NFKC', (nome or '')).strip().lower()
    nome = nome.rstrip('. \t\r\n ​')
    partes = []
    for p in nome.split('.')[1:]:
        limpo = RE_SO_EXTENSAO.sub('', p)
        if limpo:
            partes.append(limpo)
    partes.reverse()
    return partes


def _extensao_arquivo(nome):
    partes = _partes_nome(nome)
    return partes[0] if partes else ''


def anexo_perigoso(filename, mime=''):
    """
    Retorna (True, rotulo) se o documento é de um tipo usado por golpe/malware
    no WhatsApp. Confia primeiro na extensão do nome — o WhatsApp preserva o
    filename, então é o sinal mais firme — e usa o MIME como reforço.
    Containers (zip/rar) entram porque escondem o payload real.

    Bloquear aqui é IRREVERSÍVEL (a mídia expira na Meta), então a dúvida
    pende pra deixar passar e avisar — ver anexo_desconhecido().
    """
    partes = _partes_nome(filename)
    ext = partes[0] if partes else ''
    if ext in EXT_PERIGOSAS or ext in EXT_CONTAINER:
        return True, ext
    # Extensão dupla ("orcamento.js.pdf"): só as inequívocas, senão
    # "notafiscal.com.br.pdf" viraria falso positivo por causa do 'com'.
    for p in partes[1:]:
        if p in EXT_INEQUIVOCAS:
            return True, p
    # Extensão explicitamente esperada manda mais que o MIME: celular Android
    # reporta docx/xlsx como application/zip, e bloquear por isso perderia a
    # nota fiscal do cliente pra sempre.
    if ext in EXT_ESPERADAS:
        return False, ext
    m = (mime or '').split(';')[0].strip().lower()
    if m in MIME_PERIGOSOS:
        return True, ext or m
    return False, ext


# Extensões que a loja recebe de cliente o dia inteiro. O que não está aqui
# nem na lista de perigosas é "não sei o que é" — vai pro inbox com aviso
# amarelo em vez de link direto, porque é por aí que entra o tipo novo.
EXT_ESPERADAS = {
    'pdf', 'xml', 'csv', 'txt', 'rtf',
    'doc', 'docx', 'odt', 'xls', 'xlsx', 'ods', 'ppt', 'pptx', 'odp', 'odg',
    'jpg', 'jpeg', 'jfif', 'png', 'gif', 'webp', 'bmp', 'heic', 'heif',
    'tiff', 'tif',
    'mp3', 'ogg', 'oga', 'opus', 'm4a', 'aac', 'amr', 'wav', 'flac',
    'mp4', '3gp', '3gpp', 'mov', 'avi', 'mkv', 'webm', 'mpeg', 'm4v', 'wmv',
    'vcf', 'ics',
    # NF-e assinada, e-mail encaminhado, arte de fornecedor, iWork da Apple.
    'p7s', 'eml', 'msg', 'cdr', 'ai', 'eps', 'psd',
    'pages', 'numbers', 'key',
}


def anexo_desconhecido(filename, mime=''):
    """
    (True, ext) quando o anexo merece aviso em vez de link direto:

      - é de EXT_AVISO/MIME_AVISO (html, svg, Office com macro) — arma de
        golpe de verdade, mas também arquivo de trabalho legítimo;
      - ou não é nada que a gente reconheça, inclusive o caso de vir sem
        extensão com o MIME coringa 'application/octet-stream'.

    Não bloqueamos: avisamos. Bloquear por octet-stream derrubaria anexo
    legítimo em massa, mas entregar como link normal é como o próximo tipo
    de golpe entra sem ninguém desconfiar.
    """
    ext = _extensao_arquivo(filename)
    m = (mime or '').split(';')[0].strip().lower()
    if ext in EXT_AVISO or m in MIME_AVISO:
        return True, ext or m
    if ext in EXT_ESPERADAS:
        return False, ext
    if m in MIME_ESPERADOS or m.split('/')[0] in ('image', 'audio', 'video'):
        return False, ext
    return True, ext


MIME_ESPERADOS = {
    'application/pdf', 'text/plain', 'text/csv', 'text/xml', 'application/xml',
    'application/msword', 'application/vnd.ms-excel', 'application/vnd.ms-powerpoint',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'application/vnd.oasis.opendocument.text',
    'application/vnd.oasis.opendocument.spreadsheet',
    'application/vnd.oasis.opendocument.presentation',
    'application/rtf', 'text/rtf',
    'text/vcard', 'text/x-vcard', 'text/calendar',
}


def _salvar_midia_recebida(empresa, msg, media_id, mime_hint=''):
    """
    Baixa a mídia que o cliente mandou (2 passos na Meta: id → url → bytes)
    e guarda local, pra exibir no inbox. A URL da Meta expira rápido e exige
    o token no header, por isso copiamos em vez de linkar.
    Falha aqui nunca quebra o webhook — a mensagem já foi registrada.
    """
    import requests
    from django.core.files.base import ContentFile
    try:
        token = empresa.meta_access_token
        if not token:
            return
        h = {'Authorization': f'Bearer {token}'}
        info = requests.get(
            f'https://graph.facebook.com/v21.0/{media_id}', headers=h, timeout=20,
        ).json()
        url = info.get('url')
        if not url:
            logger.warning(f'[{empresa.slug}] mídia {media_id} sem url: {info}')
            return
        mime = info.get('mime_type') or mime_hint or ''
        # Backstop: nunca copiar executável/script pro servidor, mesmo que
        # a checagem por extensão tenha deixado passar.
        if (mime or '').split(';')[0].strip().lower() in MIME_PERIGOSOS:
            logger.warning(
                f'[{empresa.slug}] mídia {media_id} bloqueada por MIME perigoso: {mime}'
            )
            return
        if int(info.get('file_size') or 0) > MIDIA_MAX_BYTES:
            return
        blob = requests.get(url, headers=h, timeout=60).content
        if not blob or len(blob) > MIDIA_MAX_BYTES:
            return
        ext = MIDIA_EXT.get(mime.split(';')[0].strip(), 'bin')
        msg.midia_arquivo.save(f'{msg.id}.{ext}', ContentFile(blob), save=True)
        logger.info(f'[{empresa.slug}] mídia recebida salva: msg {msg.id} ({mime}, {len(blob)}B)')
    except Exception as e:
        logger.warning(f'[{empresa.slug}] falha ao baixar mídia {media_id}: {e}')


def _process_incoming_message(message, contacts, empresa):
    """
    Processa mensagem recebida de um cliente.
    Vincula a resposta a mensagem original mais recente para aquele telefone.
    """
    from_number = message.get('from', '')  # ex: 5516996056762
    msg_type = message.get('type', '')
    timestamp = message.get('timestamp', '')
    context = message.get('context', {})  # se for reply, tem o id da msg original
    reply_to_wamid = context.get('id', '')  # wamid da mensagem que o cliente respondeu

    # Extrair texto da mensagem
    texto = ''
    midia_id = ''
    midia_mime = ''
    if msg_type == 'text':
        texto = message.get('text', {}).get('body', '')
    elif msg_type == 'button':
        texto = message.get('button', {}).get('text', '')
    elif msg_type == 'interactive':
        interactive = message.get('interactive', {})
        if interactive.get('type') == 'button_reply':
            texto = interactive.get('button_reply', {}).get('title', '')
        elif interactive.get('type') == 'list_reply':
            texto = interactive.get('list_reply', {}).get('title', '')
    elif msg_type in ('image', 'audio', 'video', 'document', 'sticker', 'voice'):
        # Mídia do cliente: guarda o id pra baixar e mostrar no inbox
        bloco = message.get(msg_type, {}) or {}
        midia_id = bloco.get('id', '')
        midia_mime = bloco.get('mime_type', '')
        legenda = bloco.get('caption') or bloco.get('filename') or ''
        rotulo = 'image' if msg_type == 'sticker' else ('audio' if msg_type == 'voice' else msg_type)
        texto = f'[{rotulo}] {legenda}'.strip()
        # Golpe do "orçamento .js" (e .bat, .exe, .zip com payload…): documento
        # de tipo perigoso não é baixado pro servidor e vai pro inbox marcado
        # pra exibir aviso em vez de link clicável. O atendente vê o que era,
        # mas não tem como abrir por reflexo.
        # O nome do arquivo é SÓ o filename. A legenda é texto escrito pelo
        # cliente — deixar ela decidir se o anexo é seguro seria entregar a
        # chave pro golpista ("mando o .js sem filename e escrevo nota.pdf").
        nome_arq = (bloco.get('filename') or '').strip()
        caption = (bloco.get('caption') or '').strip()
        if nome_arq or msg_type == 'document':
            perigoso, rotulo_ext = anexo_perigoso(nome_arq, midia_mime)
            estranho, ext_estranha = (False, '')
            if not perigoso:
                estranho, ext_estranha = anexo_desconhecido(nome_arq, midia_mime)
            if perigoso or estranho:
                marca = (f'bloqueado:{rotulo_ext}' if perigoso
                         else f'suspeito:{ext_estranha}')
                # A legenda fica: é nela que o cliente diz "pode faturar".
                visivel = ' — '.join(p for p in (nome_arq or '(sem nome)', caption) if p)
                texto = f'[{marca}] {visivel}'
                if perigoso:
                    midia_id = ''  # impede o download em _salvar_midia_recebida
                    logger.warning(
                        f'[{empresa.slug}] anexo perigoso bloqueado de {from_number}: '
                        f'{nome_arq!r} (mime={midia_mime})'
                    )
                else:
                    logger.info(
                        f'[{empresa.slug}] anexo a confirmar de {from_number}: '
                        f'{nome_arq!r} (mime={midia_mime})'
                    )
    elif msg_type == 'unsupported':
        # A Meta manda isso quando o cliente envia algo que a Cloud API não
        # entrega (enquete, visualização única, contato, localização ao vivo…).
        # Não há conteúdo pra buscar — só avisamos o atendente do que houve.
        texto = '[sem suporte] O cliente enviou algo que o WhatsApp não repassa por aqui (enquete, visualização única, etc.)'
    else:
        texto = f'[{msg_type}]'

    # Nome do contato
    nome = ''
    if contacts:
        profile = contacts[0].get('profile', {})
        nome = profile.get('name', '')

    ts = timezone.datetime.fromtimestamp(
        int(timestamp), tz=timezone.utc
    ) if timestamp else timezone.now()

    logger.info(
        f'[{empresa.slug}] Mensagem recebida de {from_number} ({nome}): '
        f'{texto[:100]}'
    )

    # Tentar vincular a mensagem original
    msg_original = None

    # 1. Se eh reply direto, buscar pelo wamid
    if reply_to_wamid:
        msg_original = MensagemWhatsApp.objects.filter(
            empresa=empresa,
            meta_message_id=reply_to_wamid,
        ).first()

    # 2. Senao, buscar a mensagem mais recente enviada para esse numero
    if not msg_original:
        msg_original = MensagemWhatsApp.objects.filter(
            empresa=empresa,
            destinatario_telefone=from_number,
            status__in=['enviado', 'entregue', 'lido'],
        ).order_by('-created_at').first()

    if msg_original:
        msg_original.respondido = True
        msg_original.respondido_em = ts
        msg_original.resposta_texto = texto[:2000]
        msg_original.save(update_fields=[
            'respondido', 'respondido_em', 'resposta_texto',
        ])
        logger.info(
            f'Resposta vinculada a mensagem {msg_original.id} '
            f'(tipo={msg_original.tipo}, template={msg_original.template_name})'
        )

    # Registrar mensagem recebida no historico
    # Buscar customer pelo telefone
    customer = Customer.objects.filter(
        empresa=empresa,
        phone__endswith=from_number[-8:],
    ).first()

    msg_recebida = MensagemWhatsApp.objects.create(
        empresa=empresa,
        tipo='resposta_cliente',
        canal='meta',
        status='enviado',
        destinatario_nome=nome,
        destinatario_telefone=from_number,
        mensagem_texto=texto,
        meta_message_id=message.get('id', ''),
        api_response=message,
        customer=customer,
        lead=msg_original.lead if msg_original else None,
        cart=msg_original.cart if msg_original else None,
    )

    # Baixa a mídia do cliente agora (a URL da Meta expira em ~5 min) pra
    # aparecer no inbox como foto/áudio de verdade, não como "[image]".
    if midia_id:
        _salvar_midia_recebida(empresa, msg_recebida, midia_id, midia_mime)

    # Resposta automatica para o cliente (dentro da janela 24h)
    _enviar_resposta_automatica(empresa, from_number, nome)

    # Encaminhar para atendente humano via W-API
    _encaminhar_para_humano(empresa, from_number, nome, texto, msg_original)


def _enviar_resposta_automatica(empresa, telefone_cliente, nome_cliente):
    """
    Envia resposta automatica via Meta (free-form, dentro da janela 24h).
    Evita loop: so envia 1x a cada 24h por cliente.
    """
    texto = (empresa.meta_resposta_automatica or '').strip()
    if not texto:
        return

    # Variaveis disponiveis no texto da resposta automatica:
    #   {consulta}            -> link de consulta de pedido da empresa
    #   {nome}                -> nome do cliente
    #   {atendimento_oficial} -> numero oficial de atendimento ao cliente
    #   {whatsapp_humano}     -> numero do atendente (encaminhamento interno)
    atendimento = empresa.whatsapp_atendimento_oficial or empresa.meta_whatsapp_humano or ''
    texto = (
        texto
        .replace('{consulta}', empresa.link_consulta_pedido)
        .replace('{nome}', nome_cliente or '')
        .replace('{atendimento_oficial}', atendimento)
        .replace('{whatsapp_humano}', empresa.meta_whatsapp_humano or '')
    )

    janela = timezone.now() - timezone.timedelta(hours=24)
    ja_enviado = MensagemWhatsApp.objects.filter(
        empresa=empresa,
        canal='meta',
        tipo='auto_resposta',
        destinatario_telefone=telefone_cliente,
        created_at__gte=janela,
    ).exists()
    if ja_enviado:
        return

    from bling.meta_whatsapp import MetaWhatsAppClient
    client = MetaWhatsAppClient(
        phone_number_id=empresa.meta_phone_number_id,
        access_token=empresa.meta_access_token,
    )
    if not client.esta_configurado():
        return

    resultado = client.enviar_texto(telefone_cliente, texto)

    success = resultado.get('success', False)
    response_data = resultado.get('response', {}) if success else {}
    wamid = ''
    if success:
        msgs = response_data.get('messages', [])
        if msgs:
            wamid = msgs[0].get('id', '')

    MensagemWhatsApp.objects.create(
        empresa=empresa,
        tipo='auto_resposta',
        canal='meta',
        status='enviado' if success else 'falha',
        destinatario_nome=nome_cliente,
        destinatario_telefone=telefone_cliente,
        mensagem_texto=texto,
        meta_message_id=wamid,
        api_response=response_data,
        error_message=resultado.get('error', '') if not success else '',
    )

    if success:
        logger.info(f'[{empresa.slug}] Resposta automatica enviada para {telefone_cliente}')
    else:
        logger.error(f'[{empresa.slug}] Erro auto-resposta {telefone_cliente}: {resultado.get("error")}')


def _encaminhar_para_humano(empresa, telefone_cliente, nome_cliente,
                            texto_resposta, msg_original):
    """
    Quando um cliente responde uma mensagem promocional,
    envia notificacao para o WhatsApp humano da empresa
    com os dados do cliente e a resposta.
    """
    whatsapp_humano = getattr(empresa, 'meta_whatsapp_humano', '')
    if not whatsapp_humano:
        logger.info(f'[{empresa.slug}] Sem WhatsApp humano configurado, resposta nao encaminhada')
        return

    # Montar mensagem para o atendente
    tipo_original = ''
    template_original = ''
    if msg_original:
        tipo_original = msg_original.get_tipo_display()
        template_original = msg_original.template_name

    mensagem = (
        f"*Nova resposta de cliente!*\n\n"
        f"*Cliente:* {nome_cliente}\n"
        f"*Telefone:* {telefone_cliente}\n"
        f"*Respondeu a:* {tipo_original}"
    )
    if template_original:
        mensagem += f" ({template_original})"
    mensagem += f"\n\n*Mensagem:*\n{texto_resposta}\n\n"
    mensagem += f"Responda diretamente: https://wa.me/{telefone_cliente}"

    # Enviar via W-API (atendente humano usa W-API)
    from customers.services.wapi import _get_wapi_client
    client = _get_wapi_client(empresa, 'lead')
    if client.esta_configurado():
        resultado = client.enviar_mensagem(whatsapp_humano, mensagem)
        if resultado.get('success'):
            # Marcar a mensagem original como encaminhada
            if msg_original:
                msg_original.encaminhado_humano = True
                msg_original.encaminhado_humano_em = timezone.now()
                msg_original.save(update_fields=[
                    'encaminhado_humano', 'encaminhado_humano_em',
                ])
            logger.info(
                f'[{empresa.slug}] Resposta de {telefone_cliente} '
                f'encaminhada para humano {whatsapp_humano}'
            )
        else:
            logger.error(
                f'[{empresa.slug}] Erro ao encaminhar para humano: '
                f'{resultado.get("error")}'
            )
    else:
        logger.warning(f'[{empresa.slug}] W-API nao configurado para encaminhar resposta')
