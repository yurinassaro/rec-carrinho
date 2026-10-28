"""
Inbox custom estilo WhatsApp Web para conversas da Meta Cloud API.
"""
import json
import logging
import re
import requests
from datetime import timedelta
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db.models import F, Max, Count, Q, Case, When, IntegerField
from customers.models import MensagemWhatsApp, RespostaRapida
from bling.meta_whatsapp import MetaWhatsAppClient

logger = logging.getLogger(__name__)


def _carregar_templates_meta(empresa):
    """
    Busca os templates aprovados via Meta API (cached por 1h por empresa).
    Retorna dict: {nome: {body, header, footer, button_url}}.
    """
    if not empresa.meta_waba_id or not empresa.meta_access_token:
        return {}
    cache_key = f'meta_templates_{empresa.id}'
    cached = cache.get(cache_key)
    if cached:
        return cached

    templates = {}
    try:
        r = requests.get(
            f'https://graph.facebook.com/v22.0/{empresa.meta_waba_id}/message_templates',
            params={'fields': 'name,language,components', 'limit': 100},
            headers={'Authorization': f'Bearer {empresa.meta_access_token}'},
            timeout=10,
        )
        if r.ok:
            for t in r.json().get('data', []):
                info = {'body': '', 'header': '', 'footer': '', 'button_url': ''}
                for c in t.get('components', []):
                    ct = c.get('type', '')
                    if ct == 'HEADER' and c.get('format') == 'TEXT':
                        info['header'] = c.get('text', '')
                    elif ct == 'BODY':
                        info['body'] = c.get('text', '')
                    elif ct == 'FOOTER':
                        info['footer'] = c.get('text', '')
                    elif ct == 'BUTTONS':
                        for b in c.get('buttons', []):
                            if b.get('type') == 'URL':
                                info['button_url'] = f"{b.get('text', 'Botao')}: {b.get('url', '')}"
                                break
                templates[t['name']] = info
            cache.set(cache_key, templates, 3600)  # 1h
    except Exception as e:
        logger.error(f'Erro ao carregar templates Meta: {e}')

    return templates


def _renderizar_template(template_info, params):
    """Substitui {{1}}, {{2}}... com os params no body do template."""
    if not template_info:
        return ''
    body = template_info.get('body', '') or ''
    header = template_info.get('header', '') or ''
    footer = template_info.get('footer', '') or ''
    button = template_info.get('button_url', '') or ''

    # Substituir {{1}}, {{2}}, ... em body e header
    for i, val in enumerate(params or [], 1):
        body = body.replace(f'{{{{{i}}}}}', str(val))
        header = header.replace(f'{{{{{i}}}}}', str(val))

    partes = []
    if header:
        partes.append(header)
    if body:
        partes.append(body)
    if footer:
        partes.append(f'_{footer}_')
    if button:
        partes.append(f'🔗 {button}')
    return '\n\n'.join(partes)


@login_required
def inbox_view(request):
    """Pagina principal do inbox (shell SPA, dados via JSON)."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return redirect('/tenants/select/')
    return render(request, 'customers/inbox.html', {})


def _telefone_canonico(phone):
    """
    Retorna telefone normalizado pra agrupar respostas com mesmo numero
    em formatos diferentes (Meta remove o 9 na resposta inbound).
    Forma canonica: ultimos 10 digitos (DDD + 8 digitos, sem o 9 mobile).
    """
    digits = ''.join(c for c in (phone or '') if c.isdigit())
    if not digits:
        return ''
    # Remove DDI 55 se presente
    if digits.startswith('55') and len(digits) >= 12:
        digits = digits[2:]
    # Remove 9 mobile se presente (DDD + 9 + 8 = 11 digitos)
    if len(digits) == 11 and digits[2] == '9':
        digits = digits[:2] + digits[3:]
    return digits[-10:]  # garante 10 digitos finais


def _phone_variants(phone):
    """Retorna variantes do telefone (com/sem DDI, com/sem 9 mobile)."""
    digits = ''.join(c for c in (phone or '') if c.isdigit())
    if not digits:
        return [phone]
    base = digits
    if base.startswith('55') and len(base) >= 12:
        base = base[2:]
    if len(base) == 11 and base[2] == '9':
        sem9 = base[:2] + base[3:]
        com9 = base
    elif len(base) == 10:
        sem9 = base
        com9 = base[:2] + '9' + base[2:]
    else:
        sem9 = com9 = base
    return list(set([
        digits,
        '55' + com9, '55' + sem9,
        com9, sem9,
    ]))


def _dur_label(minutos):
    """Duração curta para a lista: 40min, 3h20, 2d, 3sem."""
    minutos = int(max(0, minutos))
    if minutos < 60:
        return f'{minutos}min'
    horas, resto = divmod(minutos, 60)
    if horas < 24:
        return f'{horas}h{resto:02d}' if resto else f'{horas}h'
    dias = horas // 24
    return f'{dias}d' if dias < 14 else f'{dias // 7}sem'


def _agrupar_conversas(registros, agora):
    """
    Agrupa mensagens por telefone canonico e calcula, por conversa:
      janela_aberta / janela_resta_min — a janela de 24h da Meta, contada da
      última mensagem DO CLIENTE (é o que libera mensagem livre);
      nao_respondidas / espera_desde   — mensagens do cliente ainda sem resposta
      e desde quando a mais antiga delas está esperando.

    Recebe uma lista de dicts (não um queryset) de propósito: é a parte que vale
    testar, e assim ela roda sem banco.
    """
    grupos = {}  # canon → {data}
    for m in registros:
        canon = _telefone_canonico(m['destinatario_telefone'])
        if not canon:
            continue
        g = grupos.get(canon)
        if not g:
            g = grupos[canon] = {
                'telefone': m['destinatario_telefone'],
                'canon': canon,
                'nome': '',
                'ultima_msg': '',
                'ultima_em': None,
                'tipo': '',
                'total': 0,
                'nao_respondidas': 0,
                'cliente_em': None,     # última mensagem DO CLIENTE: abre a janela
                'espera_desde': None,   # mensagem do cliente mais antiga sem resposta
            }
        g['total'] += 1
        # Preferir nome nao-vazio
        if not g['nome'] and m['destinatario_nome']:
            g['nome'] = m['destinatario_nome']
        # As listas de entrada vêm em ordens opostas, então a agregação não pode
        # depender da ordem: a "última mensagem" é sempre a de maior created_at.
        if g['ultima_em'] is None or m['created_at'] > g['ultima_em']:
            g['ultima_em'] = m['created_at']
            g['ultima_msg'] = (m['mensagem_texto'] or m['template_name'] or '')[:80]
            g['tipo'] = m['tipo']
            g['telefone'] = m['destinatario_telefone']
        if m['tipo'] == 'resposta_cliente':
            if g['cliente_em'] is None or m['created_at'] > g['cliente_em']:
                g['cliente_em'] = m['created_at']
            if not m['encaminhado_humano']:
                g['nao_respondidas'] += 1
                if g['espera_desde'] is None or m['created_at'] < g['espera_desde']:
                    g['espera_desde'] = m['created_at']

    for g in grupos.values():
        if not g['nome']:
            g['nome'] = '(sem nome)'
        resta = None
        if g['cliente_em']:
            resta = 24 * 60 - (agora - g['cliente_em']).total_seconds() / 60
        g['janela_aberta'] = bool(resta is not None and resta > 0)
        g['janela_resta_min'] = int(resta) if g['janela_aberta'] else 0
        g['espera_min'] = (
            int((agora - g['espera_desde']).total_seconds() / 60) if g['espera_desde'] else 0
        )
    return grupos


def _filtrar_ordenar_conversas(todas, filtro='', ordem=''):
    """
    filtro: ''              → todas
            nao_respondidos → só as que têm mensagem do cliente sem resposta
            janela_aberta   → só as que ainda aceitam mensagem livre
    ordem:  ''        → última mensagem primeiro (padrão)
            antigos   → quem espera há mais tempo primeiro
            janela    → janela que fecha antes primeiro
    """
    if filtro == 'nao_respondidos':
        lista = [g for g in todas if g['nao_respondidas'] > 0]
    elif filtro == 'janela_aberta':
        lista = [g for g in todas if g['janela_aberta']]
    else:
        lista = list(todas)

    if ordem == 'antigos':
        # quem está esperando resposta há mais tempo primeiro; quem não espera, no fim
        lista.sort(key=lambda g: (
            0 if g['espera_desde'] else 1,
            g['espera_desde'] or g['ultima_em'],
        ))
    elif ordem == 'janela':
        lista.sort(key=lambda g: (0 if g['janela_aberta'] else 1, g['janela_resta_min']))
    else:
        lista.sort(key=lambda g: g['ultima_em'], reverse=True)
    return lista


def _serializar_conversas(tenant, busca='', filtro='', ordem=''):
    """
    Lista de conversas agrupadas por telefone canonico (cross-formato), com a
    janela de 24h e o tempo de espera de cada uma. Ver _filtrar_ordenar_conversas
    para os valores de filtro/ordem.
    """
    agora = timezone.now()
    qs = MensagemWhatsApp.objects.filter(
        empresa=tenant, canal='meta',
    ).exclude(destinatario_telefone='')
    if busca:
        qs = qs.filter(
            Q(destinatario_nome__icontains=busca) |
            Q(destinatario_telefone__icontains=busca) |
            Q(mensagem_texto__icontains=busca)
        )

    campos = (
        'id', 'destinatario_telefone', 'destinatario_nome',
        'mensagem_texto', 'template_name', 'created_at', 'tipo',
        'encaminhado_humano',
    )

    # Coletar registros recentes (mais que 300 pra ter folga apos agrupamento)
    registros = list(qs.order_by('-created_at').values(*campos)[:3000])

    # Quem perguntou e nunca foi respondido pode ter parado há semanas e cair
    # fora das 3.000 últimas mensagens — e é exatamente essa conversa que o
    # "mais antigos" procura. Então as pendentes vêm sempre, de qualquer época.
    vistos = {m['id'] for m in registros}
    registros += [
        m for m in qs.filter(
            tipo='resposta_cliente', encaminhado_humano=False,
        ).order_by('created_at').values(*campos)[:2000]
        if m['id'] not in vistos
    ]

    todas = list(_agrupar_conversas(registros, agora).values())
    contadores = {
        'todas': len(todas),
        'nao_respondidos': sum(1 for g in todas if g['nao_respondidas'] > 0),
        'janela_aberta': sum(1 for g in todas if g['janela_aberta']),
    }
    lista = _filtrar_ordenar_conversas(todas, filtro, ordem)

    result = []
    for g in lista[:300]:
        dt_local = timezone.localtime(g['ultima_em']) if g['ultima_em'] else None
        result.append({
            'telefone': g['telefone'],
            'canon': g['canon'],
            'nome': g['nome'],
            'ultima_msg': g['ultima_msg'],
            'ultima_em_iso': dt_local.isoformat() if dt_local else '',
            'ultima_em_label': dt_local.strftime('%d/%m %H:%M') if dt_local else '',
            'tipo': g['tipo'],
            'total': g['total'],
            'nao_respondidas': g['nao_respondidas'],
            'janela_aberta': g['janela_aberta'],
            'janela_resta_min': g['janela_resta_min'],
            'janela_resta_label': _dur_label(g['janela_resta_min']) if g['janela_aberta'] else '',
            'espera_min': g['espera_min'],
            'espera_label': _dur_label(g['espera_min']) if g['nao_respondidas'] else '',
        })
    return result, contadores


def _variantes_na_base(tenant, telefone):
    """Todos os formatos do mesmo telefone que existem na base do tenant."""
    canon = _telefone_canonico(telefone)
    tels = {telefone}
    for variante in MensagemWhatsApp.objects.filter(
        empresa=tenant, canal='meta',
    ).values_list('destinatario_telefone', flat=True).distinct():
        if _telefone_canonico(variante) == canon:
            tels.add(variante)
    return tels


def _marcar_atendida(tenant, telefones):
    """
    Baixa o aviso da conversa inteira. O contador da sidebar conta mensagens DO
    CLIENTE ainda sem resposta, então marcar só a última deixava o badge preso.
    Só respondendo ou fechando a conversa — abrir para ler não baixa nada.
    """
    return MensagemWhatsApp.objects.filter(
        empresa=tenant, canal='meta',
        destinatario_telefone__in=list(telefones),
        tipo='resposta_cliente', encaminhado_humano=False,
    ).update(encaminhado_humano=True, encaminhado_humano_em=timezone.now())


# A Meta guarda a mídia recebida por ~7 dias e o webhook baixa na hora que a
# mensagem chega. Então: sem arquivo e mensagem recente = ainda pode estar
# baixando; sem arquivo e mensagem velha = a Meta já apagou, não adianta esperar.
MIDIA_JANELA_DOWNLOAD = timedelta(minutes=15)


def _estado_midia(m):
    if m.midia_arquivo:
        return 'ok'
    if m.created_at and timezone.now() - m.created_at <= MIDIA_JANELA_DOWNLOAD:
        return 'baixando'
    return 'perdida'


def _serializar_mensagem(m, texto_render):
    dt_local = timezone.localtime(m.created_at) if m.created_at else None
    return {
        'id': m.id,
        'tipo': m.tipo,
        'is_inbound': m.tipo == 'resposta_cliente',
        'texto': texto_render,
        'template_name': m.template_name or '',
        'status': m.status,
        'created_at_iso': dt_local.isoformat() if dt_local else '',
        'created_at_label': dt_local.strftime('%d/%m %H:%M') if dt_local else '',
        'midia_url': (f'/crm/inbox/midia/{m.id}/' if m.midia_arquivo else ''),
        'midia_estado': _estado_midia(m),
        # Trecho da mensagem citada, pra bolha mostrar o mesmo que o cliente vê.
        'citada': ({
            'id': m.responde_a_id,
            'autor': 'cliente' if m.responde_a.tipo == 'resposta_cliente' else 'loja',
            'trecho': (m.responde_a.mensagem_texto or m.responde_a.template_name or '')[:90],
        } if m.responde_a_id and m.responde_a else None),
    }


@login_required
def inbox_midia(request, msg_id):
    """Serve a mídia local de uma mensagem do inbox (restrita ao tenant)."""
    from django.http import FileResponse, Http404
    tenant = getattr(request, 'tenant', None)
    msg = MensagemWhatsApp.objects.filter(id=msg_id, empresa=tenant).first()
    if not msg or not msg.midia_arquivo:
        raise Http404
    import mimetypes
    nome = msg.midia_arquivo.name
    extras = {'.ogg': 'audio/ogg', '.m4a': 'audio/mp4', '.3gp': 'video/3gpp', '.amr': 'audio/amr'}
    ct = next(
        (v for k, v in extras.items() if nome.lower().endswith(k)),
        mimetypes.guess_type(nome)[0] or 'application/octet-stream',
    )
    return FileResponse(msg.midia_arquivo.open('rb'), content_type=ct)


@login_required
@require_POST
def inbox_fechar(request):
    """
    Marca a conversa como atendida sem mandar mensagem.

    Existe porque muita conversa se resolve só de ler (cliente agradecendo,
    mensagem repetida, alguém que já foi atendido no balcão). Sem isso o
    atendente precisaria responder qualquer coisa só pra tirar o aviso — e abrir
    para ler de propósito não baixa, senão a fila some sem ninguém atender.
    """
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return JsonResponse({'success': False, 'error': 'sem empresa'}, status=403)

    telefone = (request.POST.get('telefone') or '').strip()
    if not telefone:
        return JsonResponse({'success': False, 'error': 'telefone obrigatorio'}, status=400)

    baixadas = _marcar_atendida(tenant, _variantes_na_base(tenant, telefone))
    return JsonResponse({'success': True, 'baixadas': baixadas})


@login_required
def inbox_respostas_api(request):
    """
    Mensagens rápidas da empresa. Vai a lista inteira de uma vez e a busca
    acontece no navegador: são poucas centenas e assim o atendente filtra
    enquanto digita, sem esperar o servidor a cada tecla.
    """
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return JsonResponse({'respostas': []})

    # As mensagens rápidas do WhatsApp Business (as que têm atalho) vêm na
    # frente: são as que o atendimento usa de verdade. Atrás ficam as centenas
    # da base de conhecimento, que só aparecem quando ele busca por elas.
    queryset = RespostaRapida.objects.filter(empresa=tenant, ativo=True).annotate(
        sem_atalho=Case(When(atalho='', then=1), default=0, output_field=IntegerField()),
    ).order_by('sem_atalho', '-usos', 'titulo')

    respostas = [
        {'id': r.id, 'titulo': r.titulo, 'texto': r.texto, 'atalho': r.atalho}
        for r in queryset
    ]
    return JsonResponse({'respostas': respostas})


@login_required
@require_POST
def inbox_resposta_usada(request):
    """Conta o uso pra as mais usadas subirem sozinhas na lista."""
    tenant = getattr(request, 'tenant', None)
    try:
        resposta_id = int(request.POST.get('id') or 0)
    except (TypeError, ValueError):
        resposta_id = 0
    if not tenant or not resposta_id:
        return JsonResponse({'success': False}, status=400)

    RespostaRapida.objects.filter(id=resposta_id, empresa=tenant).update(
        usos=F('usos') + 1,
    )
    return JsonResponse({'success': True})


def _conversa_para_ia(tenant, telefones, limite=20):
    """
    Últimas mensagens da conversa no formato que o copiloto espera:
    [{'autor': 'cliente'|'loja', 'texto': str}] em ordem cronológica.

    Templates entram renderizados — a IA precisa ver o que o cliente leu, não
    o nome interno do template.
    """
    msgs = list(
        MensagemWhatsApp.objects.filter(
            empresa=tenant, canal='meta', destinatario_telefone__in=list(telefones),
        ).order_by('-created_at')[:limite]
    )
    msgs.reverse()

    templates_meta = _carregar_templates_meta(tenant) if any(m.template_name for m in msgs) else {}
    conversa = []
    for m in msgs:
        texto = m.mensagem_texto or ''
        if not texto and m.template_name:
            texto = _renderizar_template(
                templates_meta.get(m.template_name), m.template_params or [],
            ) or f'(template: {m.template_name})'
        if not texto.strip():
            continue
        conversa.append({
            'autor': 'cliente' if m.tipo == 'resposta_cliente' else 'loja',
            'texto': texto,
        })
    return conversa


@login_required
@require_POST
def inbox_sugerir(request):
    """
    Sugestão da IA para a conversa aberta no inbox.

    Monta a conversa a partir do banco (o inbox já tem o histórico, diferente da
    extensão que precisa ler o DOM do WhatsApp Web) e devolve o texto sugerido.
    NÃO envia: o atendente revisa, edita e decide.
    """
    from customers.permissions import modulo_liberado
    from customers.services import copiloto

    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return JsonResponse({'error': 'sem empresa'}, status=403)
    if not modulo_liberado(tenant, 'whatsapp_ia'):
        return JsonResponse({'error': 'Módulo de IA não está no seu plano'}, status=403)

    telefone = (request.POST.get('telefone') or '').strip()
    if not telefone:
        return JsonResponse({'error': 'telefone obrigatorio'}, status=400)

    todos_tels = _variantes_na_base(tenant, telefone)
    mensagens = _conversa_para_ia(tenant, todos_tels)
    ultima = MensagemWhatsApp.objects.filter(
        empresa=tenant, canal='meta', destinatario_telefone__in=list(todos_tels),
    ).order_by('-created_at').first()
    nome = (ultima.destinatario_nome if ultima else '') or ''

    try:
        resultado = copiloto.sugerir(tenant, nome, mensagens, telefone, origem='inbox')
    except copiloto.CopilotoSemContexto as e:
        return JsonResponse({'error': str(e)}, status=502)
    except copiloto.CopilotoErro as e:
        return JsonResponse({'error': str(e)}, status=502)

    return JsonResponse(resultado)


@login_required
def inbox_conversas_api(request):
    """JSON: lista de conversas."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return JsonResponse({'error': 'no tenant'}, status=400)
    busca = request.GET.get('q', '').strip()
    filtro = request.GET.get('filtro', '').strip()
    ordem = request.GET.get('ordem', '').strip()
    conversas, contadores = _serializar_conversas(tenant, busca, filtro, ordem)
    return JsonResponse({'conversas': conversas, 'contadores': contadores})


@login_required
def inbox_mensagens_api(request):
    """
    JSON: mensagens de um telefone.
    Suporta paginacao:
      ?tel=X                — primeiras 50 (mais recentes)
      ?tel=X&before_id=N    — anteriores ao id N (scroll-up)
      ?tel=X&after_id=N     — posteriores ao id N (polling new msgs)
    """
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return JsonResponse({'error': 'no tenant'}, status=400)
    tel = request.GET.get('tel', '').strip()
    if not tel:
        return JsonResponse({'error': 'tel required'}, status=400)

    before_id = request.GET.get('before_id')
    after_id = request.GET.get('after_id')

    # Busca cross-formato: encontra mensagens com qualquer variante do telefone
    # (Meta normaliza o 9 mobile na resposta inbound)
    canon = _telefone_canonico(tel)
    # Buscar todos os telefones distintos que normalizam pro mesmo canonico
    todos_tels = set([tel])
    for variant_tel in MensagemWhatsApp.objects.filter(
        empresa=tenant, canal='meta',
    ).values_list('destinatario_telefone', flat=True).distinct():
        if _telefone_canonico(variant_tel) == canon:
            todos_tels.add(variant_tel)

    base = MensagemWhatsApp.objects.filter(
        empresa=tenant, canal='meta', destinatario_telefone__in=list(todos_tels),
    ).select_related('responde_a')  # a bolha mostra o trecho citado — sem isso, 1 query por mensagem

    ids = request.GET.get('ids')
    if ids:
        # Releitura pontual: a mídia do cliente é baixada logo DEPOIS de a
        # mensagem ser criada, então a bolha já desenhada precisa se atualizar.
        try:
            lista_ids = [int(x) for x in ids.split(',') if x.strip()][:50]
        except ValueError:
            lista_ids = []
        msgs_qs = base.filter(id__in=lista_ids).order_by('created_at')
        tem_mais = False
    elif after_id:
        msgs_qs = base.filter(id__gt=int(after_id)).order_by('created_at')[:100]
        tem_mais = False
    elif before_id:
        msgs_qs = base.filter(id__lt=int(before_id)).order_by('-created_at')[:50]
        msgs_qs = list(reversed(list(msgs_qs)))
        tem_mais = base.filter(id__lt=msgs_qs[0].id).exists() if msgs_qs else False
    else:
        # Primeira carga: ultimas 50
        msgs_qs = list(reversed(list(base.order_by('-created_at')[:50])))
        tem_mais = base.exclude(id__in=[m.id for m in msgs_qs]).count() > 0 if msgs_qs else False

    templates_meta = _carregar_templates_meta(tenant)
    mensagens = []
    for m in msgs_qs:
        texto = m.mensagem_texto or ''
        if m.template_name and not texto.strip():
            tinfo = templates_meta.get(m.template_name)
            texto = _renderizar_template(tinfo, m.template_params or [])
            if not texto:
                texto = f'(template: {m.template_name})'
        mensagens.append(_serializar_mensagem(m, texto))

    # Info da conversa + janela 24h
    primeira = base.order_by('created_at').first()
    ultima_resp = base.filter(tipo='resposta_cliente').order_by('-created_at').first()
    resta_min = (
        24 * 60 - (timezone.now() - ultima_resp.created_at).total_seconds() / 60
        if ultima_resp else -1
    )
    janela_aberta = resta_min > 0
    conv_info = {
        'telefone': tel,
        'nome': (primeira.destinatario_nome if primeira else '') or '(sem nome)',
        'total': base.count(),
        'janela_aberta': janela_aberta,
        'janela_resta_min': int(resta_min) if janela_aberta else 0,
        'janela_resta_label': _dur_label(resta_min) if janela_aberta else '',
        # > 0 → a conversa está em aberto: só responder ou fechar baixa o aviso.
        'nao_respondidas': base.filter(
            tipo='resposta_cliente', encaminhado_humano=False,
        ).count(),
    }

    return JsonResponse({
        'mensagens': mensagens,
        'tem_mais': tem_mais,
        'conv_info': conv_info,
    })


def _converter_audio_para_mp3(conteudo):
    """
    Gravação do navegador (webm/opus) → MP3.

    Testado em produção 27/10/2026: o mesmo áudio em MP3 e M4A toca no celular,
    mas em OGG/Opus (o formato de nota de voz) o aparelho mostra "este áudio
    não está mais disponível". Por isso o padrão é MP3 — perde a aparência de
    nota de voz, mas o cliente CONSEGUE ouvir, que é o que importa.
    Retorna os bytes do .mp3, ou None se o ffmpeg falhar (aí segue o original).
    """
    import subprocess
    import tempfile
    import os as _os
    for args in (
        ['-c:a', 'libmp3lame', '-b:a', '64k', '-ar', '44100', '-ac', '1'],
        ['-c:a', 'libmp3lame', '-q:a', '5'],
    ):
        entrada = saida = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as f:
                f.write(conteudo)
                entrada = f.name
            saida = entrada + '.mp3'
            r = subprocess.run(
                ['ffmpeg', '-y', '-i', entrada] + args + [saida],
                capture_output=True, timeout=30,
            )
            if r.returncode == 0 and _os.path.getsize(saida) > 0:
                with open(saida, 'rb') as f:
                    return f.read()
        except Exception:
            pass
        finally:
            for p in (entrada, saida):
                try:
                    if p and _os.path.exists(p):
                        _os.unlink(p)
                except OSError:
                    pass
    return None


@login_required
@require_POST
def inbox_enviar(request):
    """
    Envia mensagem livre (texto, imagem ou audio) dentro da janela 24h.
    Aceita JSON (texto) ou multipart/form-data (com arquivo).
    """
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return JsonResponse({'success': False, 'error': 'tenant nao encontrado'}, status=400)

    # Detectar tipo de payload
    if request.content_type and request.content_type.startswith('multipart/'):
        telefone = (request.POST.get('telefone') or '').strip()
        texto = (request.POST.get('texto') or '').strip()
        arquivo = request.FILES.get('arquivo')
        responder_msg_id = (request.POST.get('responder_msg_id') or '').strip()
    else:
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'JSON invalido'}, status=400)
        telefone = (data.get('telefone') or '').strip()
        texto = (data.get('texto') or '').strip()
        arquivo = None
        responder_msg_id = str(data.get('responder_msg_id') or '').strip()

    if not telefone:
        return JsonResponse({'success': False, 'error': 'telefone obrigatorio'}, status=400)
    if not texto and not arquivo:
        return JsonResponse({'success': False, 'error': 'envie texto ou arquivo'}, status=400)

    # Verifica janela 24h (cross-formato)
    todos_tels = _variantes_na_base(tenant, telefone)

    ultima_resp = MensagemWhatsApp.objects.filter(
        empresa=tenant, canal='meta', destinatario_telefone__in=list(todos_tels),
        tipo='resposta_cliente',
    ).order_by('-created_at').first()

    if not ultima_resp or (timezone.now() - ultima_resp.created_at) >= timedelta(hours=24):
        return JsonResponse({
            'success': False,
            'error': 'Janela de 24h fechada. Cliente precisa responder antes de enviar mensagem livre.'
        }, status=400)

    # Citar a mensagem do cliente (vira "reply" no WhatsApp dele). Só aceita uma
    # mensagem desta conversa e deste tenant — o wamid não vem do cliente à toa.
    responder_a = ''
    citada = None
    if responder_msg_id:
        try:
            citada = MensagemWhatsApp.objects.filter(
                id=int(responder_msg_id), empresa=tenant, canal='meta',
                destinatario_telefone__in=list(todos_tels),
            ).first()
        except (TypeError, ValueError):
            citada = None
        responder_a = (citada.meta_message_id or '') if citada else ''

    # Cliente Meta
    client = MetaWhatsAppClient(
        phone_number_id=tenant.meta_phone_number_id,
        access_token=tenant.meta_access_token,
    )
    if not client.esta_configurado():
        return JsonResponse({'success': False, 'error': 'Meta WhatsApp nao configurado'}, status=500)

    resultado = {'success': False, 'error': 'nada enviado'}
    midia_tipo = None
    media_id = ''

    # Se tem arquivo → upload + envio midia
    if arquivo:
        mime = arquivo.content_type or 'application/octet-stream'
        # Determinar tipo Meta a partir do mime
        if mime.startswith('image/'):
            midia_tipo = 'image'
        elif mime.startswith('audio/'):
            midia_tipo = 'audio'
        elif mime.startswith('video/'):
            midia_tipo = 'video'
        else:
            midia_tipo = 'document'

        conteudo = arquivo.read()
        nome_arquivo = arquivo.name

        # O Chrome grava audio/webm, que a Meta recusa; e OGG/Opus gerado aqui
        # chegou como "áudio indisponível" no aparelho (teste 27/10). MP3 foi o
        # formato que tocou de verdade — então todo áudio sai em MP3.
        if midia_tipo == 'audio' and mime not in (
            'audio/mpeg', 'audio/mp4', 'audio/aac', 'audio/amr'
        ):
            convertido = _converter_audio_para_mp3(conteudo)
            if convertido:
                conteudo = convertido
                mime = 'audio/mpeg'
                nome_arquivo = 'audio.mp3'

        upload = client.upload_midia(conteudo, mime, filename=nome_arquivo)
        if not upload.get('success'):
            return JsonResponse({'success': False, 'error': f"Erro upload: {upload.get('error')}"}, status=500)
        media_id = upload.get('media_id', '')
        resultado = client.enviar_midia(telefone, midia_tipo, media_id,
                                        caption=texto or None, responder_a=responder_a)
    else:
        resultado = client.enviar_texto(telefone, texto, responder_a=responder_a)

    success = resultado.get('success', False)
    response_data = resultado.get('response', {}) if success else {}
    wamid = ''
    if success:
        msgs = response_data.get('messages', [])
        if msgs:
            wamid = msgs[0].get('id', '')

    # Texto da mensagem pra historico
    if midia_tipo:
        texto_hist = f'[{midia_tipo}] {texto}' if texto else f'[{midia_tipo}]'
    else:
        texto_hist = texto

    msg = MensagemWhatsApp.objects.create(
        empresa=tenant,
        tipo='atendimento_humano',
        canal='meta',
        status='enviado' if success else 'falha',
        destinatario_nome=ultima_resp.destinatario_nome if ultima_resp else '',
        destinatario_telefone=telefone,
        mensagem_texto=texto_hist,
        meta_message_id=wamid,
        api_response=response_data,
        error_message=resultado.get('error', '') if not success else '',
        responde_a=citada if responder_a else None,
    )

    # Guarda a mídia enviada (áudio/imagem) pra tocar/ver no próprio inbox
    if success and arquivo and midia_tipo in ('audio', 'image', 'video') and len(conteudo) <= 16 * 1024 * 1024:
        from django.core.files.base import ContentFile
        ext = nome_arquivo.rsplit('.', 1)[-1].lower() if '.' in nome_arquivo else 'bin'
        try:
            msg.midia_arquivo.save(f'{msg.id}.{ext}', ContentFile(conteudo), save=True)
        except Exception:
            pass  # replay no inbox é cosmético — o envio em si já foi feito

    if success and ultima_resp:
        _marcar_atendida(tenant, todos_tels)

    # Devolve a mensagem já pronta pra tela. Sem isso o navegador precisava de um
    # SEGUNDO request só pra buscar o que acabou de mandar — e cada ida e volta
    # daqui até o atendente custa ~200ms.
    return JsonResponse({
        'success': success,
        'error': resultado.get('error', ''),
        'wamid': wamid,
        'tipo': midia_tipo or 'text',
        'mensagem': _serializar_mensagem(msg, msg.mensagem_texto) if success else None,
    })
