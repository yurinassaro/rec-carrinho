"""
API endpoint para a extensão Chrome do WhatsApp Web.
Recebe contatos capturados do WhatsApp Web e salva no CRM com pipeline.
"""
import hashlib
import logging
import re
import json
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from tenants.models import Empresa
from customers.models import Lead, Customer, Pipeline, PipelineEtapa, ContatoPipeline

logger = logging.getLogger(__name__)


def _validar_api_key(request, empresa):
    """Valida a API key da extensão Chrome."""
    api_key = request.headers.get('X-API-Key', '')
    if not api_key:
        return False
    expected = hashlib.sha256(
        f"{empresa.slug}:{empresa.woo_webhook_secret}".encode()
    ).hexdigest()[:32]
    return api_key == expected


def _limpar_telefone(telefone):
    """Limpa e formata telefone."""
    phone = re.sub(r'\D', '', telefone)
    if len(phone) < 10:
        return None
    if not phone.startswith('55'):
        phone = f'55{phone}'
    return phone


def _get_empresa_or_error(empresa_slug):
    try:
        return Empresa.objects.get(slug=empresa_slug, ativo=True), None
    except Empresa.DoesNotExist:
        return None, JsonResponse({'error': 'Empresa não encontrada'}, status=404)


@csrf_exempt
@require_http_methods(["GET"])
def chrome_extension_pipelines(request, empresa_slug):
    """
    GET /api/v1/leads/chrome-extension/<slug>/pipelines/
    Lista pipelines e etapas da empresa.
    """
    empresa, error = _get_empresa_or_error(empresa_slug)
    if error:
        return error
    if not _validar_api_key(request, empresa):
        return JsonResponse({'error': 'API key inválida'}, status=401)

    pipelines = Pipeline.objects.filter(empresa=empresa, ativo=True).prefetch_related('etapas')

    data = []
    for p in pipelines:
        data.append({
            'id': p.id,
            'nome': p.nome,
            'slug': p.slug,
            'etapas': [
                {
                    'id': e.id,
                    'nome': e.nome,
                    'slug': e.slug,
                    'cor': e.cor,
                }
                for e in p.etapas.all()
            ]
        })

    return JsonResponse({'pipelines': data})


@csrf_exempt
@require_http_methods(["POST"])
def chrome_extension_lead(request, empresa_slug):
    """
    POST /api/v1/leads/chrome-extension/<slug>/
    Recebe contato do WhatsApp Web e salva no pipeline.

    Body JSON:
    {
        "telefone": "11999999999",
        "nome": "João Silva",
        "pipeline_id": 1,        // opcional
        "etapa_id": 2,           // opcional
        "notas": "texto livre",  // opcional
        "tags": ["whatsapp-web"] // opcional
    }
    """
    empresa, error = _get_empresa_or_error(empresa_slug)
    if error:
        return error
    if not _validar_api_key(request, empresa):
        return JsonResponse({'error': 'API key inválida'}, status=401)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)

    telefone = data.get('telefone', '').strip()
    nome = data.get('nome', '').strip()
    pipeline_id = data.get('pipeline_id')
    etapa_id = data.get('etapa_id')
    notas = data.get('notas', '').strip()
    tags = data.get('tags', [])

    if not telefone:
        return JsonResponse({'error': 'Telefone é obrigatório'}, status=400)
    if not nome:
        nome = 'Contato WhatsApp'

    telefone_limpo = _limpar_telefone(telefone)
    if not telefone_limpo:
        return JsonResponse({'error': 'Telefone inválido'}, status=400)

    phone_suffix = telefone_limpo[-8:]

    # Verificar se já é customer
    customer = Customer.objects.filter(
        empresa=empresa,
        phone__endswith=phone_suffix,
    ).first()

    # Se tem pipeline, salvar como ContatoPipeline
    if pipeline_id:
        pipeline = Pipeline.objects.filter(id=pipeline_id, empresa=empresa).first()
        if not pipeline:
            return JsonResponse({'error': 'Pipeline não encontrado'}, status=400)

        etapa = None
        if etapa_id:
            etapa = PipelineEtapa.objects.filter(id=etapa_id, pipeline=pipeline).first()
        if not etapa:
            etapa = pipeline.etapas.first()

        # Verificar duplicata no pipeline
        existente = ContatoPipeline.objects.filter(
            empresa=empresa,
            pipeline=pipeline,
            telefone__endswith=phone_suffix,
        ).first()

        if existente:
            return JsonResponse({
                'status': 'existing',
                'message': f'Já existe no pipeline {pipeline.nome}: {existente.nome}',
                'contato_id': existente.id,
                'pipeline': pipeline.nome,
                'etapa': existente.etapa.nome if existente.etapa else None,
            })

        contato = ContatoPipeline.objects.create(
            empresa=empresa,
            pipeline=pipeline,
            etapa=etapa,
            nome=nome,
            telefone=telefone_limpo,
            customer=customer,
            notas=notas,
            origem='chrome_extension',
            tags=tags or ['whatsapp-web', 'chrome-extension'],
        )

        logger.info(f"[Chrome Extension] Contato pipeline criado: {nome} - {telefone_limpo} - pipeline={pipeline.nome} - empresa={empresa.slug}")

        return JsonResponse({
            'status': 'created',
            'message': f'{nome} salvo no pipeline {pipeline.nome}',
            'contato_id': contato.id,
            'pipeline': pipeline.nome,
            'etapa': etapa.nome if etapa else None,
            'is_customer': customer is not None,
        }, status=201)

    # Sem pipeline — salvar como Lead (comportamento original)
    lead_existente = Lead.objects.filter(
        empresa=empresa,
        whatsapp__endswith=phone_suffix,
    ).first()

    if lead_existente:
        return JsonResponse({
            'status': 'existing',
            'message': f'Lead já existe: {lead_existente.nome}',
            'lead_id': lead_existente.id,
            'lead_status': lead_existente.get_status_display(),
        })

    is_customer = customer is not None
    lead_status = 'customer' if is_customer else 'new'
    form_id = f"chrome-{telefone_limpo}-{int(timezone.now().timestamp())}"

    lead = Lead.objects.create(
        empresa=empresa,
        form_id=form_id,
        nome=nome,
        whatsapp=telefone_limpo,
        numero_sapato='',
        status=lead_status,
        is_customer=is_customer,
        related_customer=customer,
        created_at=timezone.now(),
        notes=notas or "Capturado via extensão Chrome WhatsApp Web.",
    )

    logger.info(f"[Chrome Extension] Lead criado: {lead.nome} - {lead.whatsapp} - empresa={empresa.slug}")

    return JsonResponse({
        'status': 'created',
        'message': f'Lead salvo: {nome}',
        'lead_id': lead.id,
        'is_customer': is_customer,
        'lead_status': lead.get_status_display(),
    }, status=201)


@csrf_exempt
@require_http_methods(["GET"])
def chrome_extension_check(request, empresa_slug):
    """
    GET /api/v1/leads/chrome-extension/<slug>/check/?telefone=11999999999
    Verifica se telefone já existe na base.
    """
    empresa, error = _get_empresa_or_error(empresa_slug)
    if error:
        return error
    if not _validar_api_key(request, empresa):
        return JsonResponse({'error': 'API key inválida'}, status=401)

    telefone = request.GET.get('telefone', '').strip()
    if not telefone:
        return JsonResponse({'error': 'Telefone é obrigatório'}, status=400)

    telefone_limpo = _limpar_telefone(telefone)
    if not telefone_limpo:
        return JsonResponse({'error': 'Telefone inválido'}, status=400)

    phone_suffix = telefone_limpo[-8:]

    lead = Lead.objects.filter(empresa=empresa, whatsapp__endswith=phone_suffix).first()
    customer = Customer.objects.filter(empresa=empresa, phone__endswith=phone_suffix).first()
    contatos = ContatoPipeline.objects.filter(empresa=empresa, telefone__endswith=phone_suffix).select_related('pipeline', 'etapa')

    pipelines_info = [
        {
            'pipeline': c.pipeline.nome,
            'etapa': c.etapa.nome if c.etapa else None,
        }
        for c in contatos
    ]

    return JsonResponse({
        'exists': lead is not None or customer is not None or contatos.exists(),
        'is_lead': lead is not None,
        'is_customer': customer is not None,
        'lead_nome': lead.nome if lead else None,
        'lead_status': lead.get_status_display() if lead else None,
        'customer_nome': customer.full_name if customer else None,
        'customer_status': customer.get_status_display() if customer else None,
        'pipelines': pipelines_info,
    })
