"""
API de triagem de atendimento por IA (extensão Chrome → backend → Sonnet).

A extensão lê a lista de conversas do WhatsApp Web (nome + última mensagem
completa + quem mandou) e manda o lote aqui. O backend classifica cada conversa
com o Claude Sonnet e devolve quem precisa de atendente humano.

Fase 1 (dry-run): a extensão apenas LOGA o resultado, não marca nada.
"""
import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from customers.api_chrome_extension import (
    _validar_api_key, _get_empresa_or_error, _limpar_telefone,
)
from customers.services.triagem_ia import classificar_lote
from customers.models import Pipeline, PipelineEtapa, ContatoPipeline, Customer
from customers.permissions import exige_modulo

logger = logging.getLogger(__name__)

MAX_CONVERSAS = 160  # trava de custo por requisição (~$0,32 no pior caso)
PIPELINE_ATENDIMENTO = "atendimento"


@csrf_exempt
@require_http_methods(["POST"])
@exige_modulo('whatsapp_ia')
def chrome_extension_triagem(request, empresa_slug):
    """
    POST /api/v1/leads/chrome-extension/<slug>/triagem/

    Body JSON:
    {
        "conversas": [
            {"id": "row-0", "nome": "Fulano", "ultima_msg": "...", "autor": "cliente"},
            ...
        ]
    }

    Retorna:
    {
        "resultados": [
            {"id": "row-0", "nome": "Fulano", "precisa_humano": true,
             "motivo": "...", "urgencia": "alta"},
            ...
        ],
        "total": N, "precisam": M
    }
    """
    empresa, error = _get_empresa_or_error(empresa_slug)
    if error:
        return error
    if not _validar_api_key(request, empresa):
        return JsonResponse({'error': 'API key inválida'}, status=401)

    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)

    conversas = data.get('conversas', [])
    if not isinstance(conversas, list) or not conversas:
        return JsonResponse({'error': 'Envie "conversas" (lista não vazia).'}, status=400)

    if len(conversas) > MAX_CONVERSAS:
        logger.warning(
            f"[Triagem IA] {empresa.slug}: lote de {len(conversas)} truncado para {MAX_CONVERSAS}"
        )
        conversas = conversas[:MAX_CONVERSAS]

    try:
        resultados = classificar_lote(conversas)
    except Exception as e:
        logger.exception("[Triagem IA] Falha geral na classificação")
        return JsonResponse({'error': f'Erro na IA: {e}'}, status=502)

    precisam = sum(1 for r in resultados if r.get('precisa_humano'))
    logger.info(
        f"[Triagem IA] {empresa.slug}: {len(resultados)} conversas, {precisam} precisam de humano"
    )

    return JsonResponse({
        'resultados': resultados,
        'total': len(resultados),
        'precisam': precisam,
    })


@csrf_exempt
@require_http_methods(["POST"])
@exige_modulo('whatsapp_ia')
def chrome_extension_sugerir(request, empresa_slug):
    """
    POST /api/v1/leads/chrome-extension/<slug>/sugerir/  (Copiloto)

    A extensão abre uma conversa no WhatsApp Web, lê as últimas mensagens do
    DOM e manda aqui. Devolvemos a resposta SUGERIDA (o atendente revisa e
    envia — nunca enviamos sozinhos).

    Body: {"nome": "Fulano", "mensagens": [{"autor": "cliente"|"loja", "texto": "..."}]}
    Retorna: {"resposta": "...", "confianca": "alta|media|baixa", "observacao": "..."}
    """
    from customers.services import copiloto

    empresa, error = _get_empresa_or_error(empresa_slug)
    if error:
        return error
    if not _validar_api_key(request, empresa):
        return JsonResponse({'error': 'API key inválida'}, status=401)

    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)

    mensagens = data.get('mensagens', [])
    if not isinstance(mensagens, list):
        mensagens = []
    nome = (data.get('nome') or '').strip()
    telefone = (data.get('telefone') or '').strip()
    # Bank-first: sem mensagens do DOM mas COM telefone, a Ana reconstrói a
    # conversa do banco dela. Só recusa se não tiver nem um nem outro.
    if not mensagens and not telefone:
        return JsonResponse({'error': 'Envie "mensagens" ou "telefone".'}, status=400)

    # Ana primeiro, Claude local como rede de segurança — ver services/copiloto.py.
    try:
        return JsonResponse(copiloto.sugerir(empresa, nome, mensagens, telefone, origem='extensao'))
    except copiloto.CopilotoSemContexto as e:
        return JsonResponse({'error': f'{e} na tela'}, status=502)
    except copiloto.CopilotoErro as e:
        return JsonResponse({'error': str(e)}, status=502)


@csrf_exempt
@require_http_methods(["POST"])
@exige_modulo('whatsapp_ia')
def chrome_extension_crm_triagem(request, empresa_slug):
    """
    POST /api/v1/leads/chrome-extension/<slug>/crm-triagem/

    Cria/atualiza um card na pipeline "Atendimento" para um contato que a IA
    apontou como precisando de atendente.

    Body: {nome, telefone, etapa_slug, motivo, urgencia}
    """
    empresa, error = _get_empresa_or_error(empresa_slug)
    if error:
        return error
    if not _validar_api_key(request, empresa):
        return JsonResponse({'error': 'API key inválida'}, status=401)

    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)

    nome = (data.get('nome') or '').strip() or 'Contato WhatsApp'
    telefone_raw = (data.get('telefone') or '').strip()
    etapa_slug = (data.get('etapa_slug') or 'esperando-compras').strip()
    motivo = (data.get('motivo') or '').strip()
    urgencia = (data.get('urgencia') or '').strip()

    pipeline = Pipeline.objects.filter(empresa=empresa, slug=PIPELINE_ATENDIMENTO).first()
    if not pipeline:
        return JsonResponse({'error': 'Pipeline Atendimento não existe'}, status=400)

    etapa = pipeline.etapas.filter(slug=etapa_slug).first() or pipeline.etapas.first()

    telefone = _limpar_telefone(telefone_raw) if telefone_raw else None
    nota = f"[Triagem IA] {urgencia.upper()}: {motivo}" if motivo else ""

    # Evita duplicar: por telefone se tiver; senão por NOME (conversas sem número,
    # ex: "Problemas Clientes", "Cliente Hernani" — também viram card).
    existente = None
    if telefone:
        existente = ContatoPipeline.objects.filter(
            empresa=empresa, pipeline=pipeline,
            telefone__endswith=telefone[-8:],
        ).first()
    else:
        existente = ContatoPipeline.objects.filter(
            empresa=empresa, pipeline=pipeline,
            telefone='', nome=nome,
        ).first()

    if existente:
        existente.etapa = etapa
        if nota:
            existente.notas = f"{nota}\n{existente.notas or ''}".strip()
        existente.save(update_fields=['etapa', 'notas', 'updated_at'])
        return JsonResponse({'status': 'updated', 'contato_id': existente.id, 'etapa': etapa.nome})

    customer = None
    if telefone:
        customer = Customer.objects.filter(empresa=empresa, phone__endswith=telefone[-8:]).first()

    contato = ContatoPipeline.objects.create(
        empresa=empresa, pipeline=pipeline, etapa=etapa,
        nome=nome, telefone=telefone or '', customer=customer,
        notas=nota, origem='triagem_ia',
        tags=['whatsapp-web', 'triagem-ia', urgencia] if urgencia else ['triagem-ia'],
    )
    return JsonResponse({'status': 'created', 'contato_id': contato.id, 'etapa': etapa.nome})


@csrf_exempt
@require_http_methods(["POST"])
@exige_modulo('whatsapp_ia')
def chrome_extension_ficou_pra_tras(request, empresa_slug):
    """
    POST /api/v1/leads/chrome-extension/<slug>/ficou-pra-tras/

    RADAR: pede pra Ana (neuraxo) a lista de clientes que ficaram pra trás
    (filtro de tempo + IA, dentro do horário de suporte). Devolve a lista pro
    extensor pintar 🔔 / marcar não-lido / jogar no CRM.

    Body (opcional): {hora_ini, hora_fim, horas_esperando, dias_sumido, limite, usar_ia}
    """
    from customers.services import neuraxo_copilot

    empresa, error = _get_empresa_or_error(empresa_slug)
    if error:
        return error
    if not _validar_api_key(request, empresa):
        return JsonResponse({'error': 'API key inválida'}, status=401)
    if not neuraxo_copilot.neuraxo_ativo(empresa):
        return JsonResponse({'error': 'IA (neuraxo-agent) não configurada para esta empresa'}, status=400)

    try:
        params = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        params = {}

    try:
        data = neuraxo_copilot.radar_via_neuraxo(empresa, params)
    except Exception as e:
        logger.warning(f"[Radar] {empresa.slug}: falha no neuraxo ({e})")
        return JsonResponse({'error': f'Radar indisponível: {e}'}, status=502)

    # O CRM é o dono: grava os cards no pipeline (task agendada e botão manual
    # escrevem no MESMO lugar; a extensão só lê via classificacoes/).
    if not data.get('fora_horario') and data.get('itens'):
        try:
            from customers.services.radar_crm import sincronizar_classificacoes
            sincronizar_classificacoes(empresa, data['itens'])
        except Exception:
            logger.exception(f"[Radar] {empresa.slug}: falha ao gravar cards no CRM")
    # Campo novo da Ana: 'resolvidos' = quem a loja respondeu → resolve o card já
    if data.get('resolvidos'):
        try:
            from customers.services.radar_crm import resolver_classificacao
            for r in data['resolvidos']:
                tel = r if isinstance(r, str) else (r.get('telefone') or '')
                if tel:
                    resolver_classificacao(empresa, tel)
        except Exception:
            logger.exception(f"[Radar] {empresa.slug}: falha ao resolver 'resolvidos'")

    logger.info(f"[Radar] {empresa.slug}: {data.get('total', 0)} ficaram pra trás "
                f"(fora_horario={data.get('fora_horario')})")
    return JsonResponse(data)


@csrf_exempt
@require_http_methods(["POST"])
@exige_modulo('whatsapp_ia')
def chrome_extension_copiloto_feedback(request, empresa_slug):
    """
    POST .../copiloto-feedback/ — fecha o ciclo de TREINO da Ana.

    A extensão reporta o que o vendedor realmente ENVIOU depois de ver a sugestão:
      enviado == sugestao → a Ana acertou (reforço)
      enviado != sugestao → a versão editada vira o novo gabarito (correção)

    Body: {"pergunta": "...", "sugestao": "...", "enviado": "...", "categoria": "geral"}
    """
    from customers.services import neuraxo_copilot

    empresa, error = _get_empresa_or_error(empresa_slug)
    if error:
        return error
    if not _validar_api_key(request, empresa):
        return JsonResponse({'error': 'API key inválida'}, status=401)
    if not neuraxo_copilot.neuraxo_ativo(empresa):
        return JsonResponse({'status': 'skipped', 'motivo': 'neuraxo não configurado'})

    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)

    pergunta = (data.get('pergunta') or '').strip()
    enviado = (data.get('enviado') or '').strip()
    if not pergunta or not enviado:
        return JsonResponse({'error': '"pergunta" e "enviado" são obrigatórios'}, status=400)

    try:
        r = neuraxo_copilot.feedback_via_neuraxo(
            empresa, pergunta, (data.get('sugestao') or '').strip(),
            enviado, (data.get('categoria') or 'geral').strip())
        logger.info(f"[Treino] {empresa.slug}: feedback {r.get('resultado')}")
        return JsonResponse({'status': 'ok', 'resultado': r.get('resultado')})
    except Exception as e:
        logger.warning(f"[Treino] {empresa.slug}: falha no feedback ({e})")
        return JsonResponse({'status': 'erro', 'error': str(e)[:200]}, status=502)


@csrf_exempt
@require_http_methods(["GET"])
@exige_modulo('whatsapp_ia')
def chrome_extension_audio_fila(request, empresa_slug):
    """
    GET .../audio-fila/ — fila de áudios aprovados aguardando ENVIO MANUAL.
    A extensão baixa cada áudio, anexa na conversa e o HUMANO aperta enviar.
    """
    from customers.services import neuraxo_copilot

    empresa, error = _get_empresa_or_error(empresa_slug)
    if error:
        return error
    if not _validar_api_key(request, empresa):
        return JsonResponse({'error': 'API key inválida'}, status=401)
    if not neuraxo_copilot.neuraxo_ativo(empresa):
        return JsonResponse({'total': 0, 'itens': []})
    try:
        data = neuraxo_copilot.fila_audio_via_neuraxo(empresa)
    except Exception as e:
        logger.warning(f"[FilaAudio] {empresa.slug}: {e}")
        return JsonResponse({'error': f'Fila indisponível: {e}'}, status=502)
    # Blocklist 🚫: quem o Yuri marcou como Ignorar sai da fila (mesmo aprovado lá)
    from customers.services.radar_crm import sufixos_ignorados
    import re as _re
    bloq = sufixos_ignorados(empresa)
    if bloq:
        antes = len(data.get('itens', []))
        data['itens'] = [i for i in data.get('itens', [])
                         if _re.sub(r'\D', '', i.get('telefone') or '')[-8:] not in bloq]
        data['total'] = len(data['itens'])
        if antes != data['total']:
            logger.info(f"[FilaAudio] {empresa.slug}: {antes - data['total']} bloqueado(s) pela lista Ignorar")
    return JsonResponse(data)


@csrf_exempt
@require_http_methods(["POST"])
@exige_modulo('whatsapp_ia')
def chrome_extension_audio_confirmar(request, empresa_slug):
    """
    POST .../audio-confirmar/ — o humano ENVIOU o áudio; repassa pro neuraxo
    ({item_id}), que grava na conversa e avisa o CRM.
    """
    from customers.services import neuraxo_copilot

    empresa, error = _get_empresa_or_error(empresa_slug)
    if error:
        return error
    if not _validar_api_key(request, empresa):
        return JsonResponse({'error': 'API key inválida'}, status=401)
    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)
    item_id = data.get('item_id')
    if not item_id:
        return JsonResponse({'error': 'item_id obrigatório'}, status=400)
    try:
        return JsonResponse(neuraxo_copilot.confirmar_audio_via_neuraxo(empresa, item_id))
    except Exception as e:
        logger.warning(f"[FilaAudio] {empresa.slug}: confirmar falhou ({e})")
        return JsonResponse({'error': str(e)[:200]}, status=502)


@csrf_exempt
@require_http_methods(["GET"])
@exige_modulo('whatsapp_ia')
def chrome_extension_audio_biblioteca(request, empresa_slug):
    """
    GET .../audio-biblioteca/ — metadados da biblioteca de áudios aprovados
    (sync por BOTÃO na extensão; nenhum .ogg passa por aqui, só ~1KB de JSON).
    """
    from customers.services import neuraxo_copilot

    empresa, error = _get_empresa_or_error(empresa_slug)
    if error:
        return error
    if not _validar_api_key(request, empresa):
        return JsonResponse({'error': 'API key inválida'}, status=401)
    if not neuraxo_copilot.neuraxo_ativo(empresa):
        return JsonResponse({'total': 0, 'audios': []})
    try:
        return JsonResponse(neuraxo_copilot.biblioteca_audio_via_neuraxo(empresa))
    except Exception as e:
        logger.warning(f"[BibAudio] {empresa.slug}: {e}")
        return JsonResponse({'error': f'Biblioteca indisponível: {e}'}, status=502)


@csrf_exempt
@require_http_methods(["POST"])
def chrome_extension_ignorar_classificacao(request, empresa_slug):
    """
    POST .../ignorar-classificacao/ — BLOCKLIST: tira o contato da lista pra
    sempre (etapa 🚫 Ignorar no pipeline do radar). A Ana pode classificar de
    novo, mas o CRM descarta: não pinta, não marca não-lido, não entra na fila
    de áudio. Pra reativar: arraste o card pra fora da coluna 🚫 no CRM.

    Body: {"telefone": "5516...", "nome": "Fulano"}
    """
    from customers.services.radar_crm import ignorar_contato

    empresa, error = _get_empresa_or_error(empresa_slug)
    if error:
        return error
    if not _validar_api_key(request, empresa):
        return JsonResponse({'error': 'API key inválida'}, status=401)
    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)
    tel = (data.get('telefone') or '').strip()
    nome = (data.get('nome') or '').strip()
    if not tel and not nome:
        return JsonResponse({'error': 'informe telefone ou nome'}, status=400)
    ok = ignorar_contato(empresa, tel, nome)
    logger.info(f"[Ignorar] {empresa.slug}: {nome or tel} → blocklist ({ok})")
    return JsonResponse({'status': 'ok' if ok else 'erro'})
