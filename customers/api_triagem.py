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

logger = logging.getLogger(__name__)

MAX_CONVERSAS = 160  # trava de custo por requisição (~$0,32 no pior caso)
PIPELINE_ATENDIMENTO = "atendimento"


@csrf_exempt
@require_http_methods(["POST"])
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
def chrome_extension_sugerir(request, empresa_slug):
    """
    POST /api/v1/leads/chrome-extension/<slug>/sugerir/  (Copiloto)

    A extensão abre uma conversa no WhatsApp Web, lê as últimas mensagens do
    DOM e manda aqui. Devolvemos a resposta SUGERIDA (o atendente revisa e
    envia — nunca enviamos sozinhos).

    Body: {"nome": "Fulano", "mensagens": [{"autor": "cliente"|"loja", "texto": "..."}]}
    Retorna: {"resposta": "...", "confianca": "alta|media|baixa", "observacao": "..."}
    """
    from customers.services.sugestao_ia import sugerir_resposta

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
    if not isinstance(mensagens, list) or not mensagens:
        return JsonResponse({'error': 'Envie "mensagens" (lista não vazia).'}, status=400)

    nome = (data.get('nome') or '').strip()
    try:
        s = sugerir_resposta(nome, mensagens, nome_loja=empresa.nome)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        logger.exception("[Copiloto] Falha na sugestão")
        return JsonResponse({'error': f'Erro na IA: {e}'}, status=502)

    logger.info(f"[Copiloto] {empresa.slug}: sugestão pra '{nome}' (confiança {s.confianca})")
    return JsonResponse({
        'resposta': s.resposta,
        'confianca': s.confianca,
        'observacao': s.observacao,
    })


@csrf_exempt
@require_http_methods(["POST"])
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
