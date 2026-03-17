"""
Views do CRM - Kanban Board com Pipelines.
Acessível via /crm/ para usuários logados.
"""
import json
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_http_methods
from django.utils import timezone
from django.db.models import Count, Sum, Q
from customers.models import Pipeline, PipelineEtapa, ContatoPipeline


@login_required
def crm_kanban(request):
    """View principal do CRM - Kanban Board."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return redirect('/tenants/select/')

    pipelines = Pipeline.objects.filter(empresa=tenant, ativo=True).prefetch_related('etapas')
    pipeline_id = request.GET.get('pipeline')

    pipeline_atual = None
    etapas_data = []

    if pipeline_id:
        pipeline_atual = pipelines.filter(id=pipeline_id).first()
    if not pipeline_atual and pipelines.exists():
        pipeline_atual = pipelines.first()

    if pipeline_atual:
        etapas = pipeline_atual.etapas.all().order_by('ordem')
        for etapa in etapas:
            contatos = ContatoPipeline.objects.filter(
                empresa=tenant,
                pipeline=pipeline_atual,
                etapa=etapa,
            ).order_by('-created_at')

            etapas_data.append({
                'etapa': etapa,
                'contatos': contatos,
                'total': contatos.count(),
                'valor_total': contatos.aggregate(total=Sum('valor_estimado'))['total'] or 0,
            })

    # Stats gerais
    if pipeline_atual:
        total_contatos = ContatoPipeline.objects.filter(
            empresa=tenant, pipeline=pipeline_atual
        ).count()
        total_valor = ContatoPipeline.objects.filter(
            empresa=tenant, pipeline=pipeline_atual
        ).aggregate(total=Sum('valor_estimado'))['total'] or 0
        contatos_hoje = ContatoPipeline.objects.filter(
            empresa=tenant, pipeline=pipeline_atual,
            created_at__date=timezone.now().date()
        ).count()
    else:
        total_contatos = total_valor = contatos_hoje = 0

    return render(request, 'customers/crm_kanban.html', {
        'empresa': tenant,
        'pipelines': pipelines,
        'pipeline_atual': pipeline_atual,
        'etapas_data': etapas_data,
        'total_contatos': total_contatos,
        'total_valor': total_valor,
        'contatos_hoje': contatos_hoje,
    })


@login_required
@require_POST
def crm_mover_contato(request):
    """Move contato para outra etapa (drag-and-drop)."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return JsonResponse({'error': 'Sem empresa'}, status=400)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)

    contato_id = data.get('contato_id')
    etapa_id = data.get('etapa_id')

    contato = get_object_or_404(ContatoPipeline, id=contato_id, empresa=tenant)
    etapa = get_object_or_404(PipelineEtapa, id=etapa_id, pipeline=contato.pipeline)

    contato.etapa = etapa
    contato.save(update_fields=['etapa', 'updated_at'])

    return JsonResponse({
        'status': 'ok',
        'contato_id': contato.id,
        'etapa': etapa.nome,
    })


@login_required
@require_POST
def crm_criar_contato(request):
    """Cria novo contato no pipeline."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return JsonResponse({'error': 'Sem empresa'}, status=400)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)

    pipeline_id = data.get('pipeline_id')
    etapa_id = data.get('etapa_id')
    nome = data.get('nome', '').strip()
    telefone = data.get('telefone', '').strip()
    email = data.get('email', '').strip()
    empresa_contato = data.get('empresa_contato', '').strip()
    notas = data.get('notas', '').strip()
    prioridade = data.get('prioridade', 'media')
    valor_estimado = data.get('valor_estimado')

    if not nome:
        return JsonResponse({'error': 'Nome é obrigatório'}, status=400)

    pipeline = get_object_or_404(Pipeline, id=pipeline_id, empresa=tenant)
    etapa = None
    if etapa_id:
        etapa = get_object_or_404(PipelineEtapa, id=etapa_id, pipeline=pipeline)
    if not etapa:
        etapa = pipeline.etapas.first()

    contato = ContatoPipeline.objects.create(
        empresa=tenant,
        pipeline=pipeline,
        etapa=etapa,
        nome=nome,
        telefone=telefone,
        email=email,
        empresa_contato=empresa_contato,
        notas=notas,
        prioridade=prioridade,
        valor_estimado=valor_estimado if valor_estimado else None,
        origem='manual',
    )

    return JsonResponse({
        'status': 'created',
        'contato': {
            'id': contato.id,
            'nome': contato.nome,
            'telefone': contato.telefone,
            'etapa': etapa.nome if etapa else None,
        }
    }, status=201)


@login_required
@require_POST
def crm_editar_contato(request):
    """Edita contato existente."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return JsonResponse({'error': 'Sem empresa'}, status=400)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)

    contato_id = data.get('contato_id')
    contato = get_object_or_404(ContatoPipeline, id=contato_id, empresa=tenant)

    fields_to_update = []
    for field in ['nome', 'telefone', 'email', 'empresa_contato', 'notas', 'prioridade', 'responsavel']:
        if field in data:
            setattr(contato, field, data[field])
            fields_to_update.append(field)

    if 'valor_estimado' in data:
        contato.valor_estimado = data['valor_estimado'] if data['valor_estimado'] else None
        fields_to_update.append('valor_estimado')

    if 'proximo_contato' in data:
        contato.proximo_contato = data['proximo_contato'] if data['proximo_contato'] else None
        fields_to_update.append('proximo_contato')

    if fields_to_update:
        fields_to_update.append('updated_at')
        contato.save(update_fields=fields_to_update)

    return JsonResponse({'status': 'ok', 'contato_id': contato.id})


@login_required
@require_POST
def crm_deletar_contato(request):
    """Remove contato do pipeline."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return JsonResponse({'error': 'Sem empresa'}, status=400)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)

    contato_id = data.get('contato_id')
    contato = get_object_or_404(ContatoPipeline, id=contato_id, empresa=tenant)
    contato.delete()

    return JsonResponse({'status': 'deleted'})


@login_required
@require_POST
def crm_criar_pipeline(request):
    """Cria novo pipeline com etapas padrão."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return JsonResponse({'error': 'Sem empresa'}, status=400)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)

    nome = data.get('nome', '').strip()
    if not nome:
        return JsonResponse({'error': 'Nome é obrigatório'}, status=400)

    from django.utils.text import slugify
    slug = slugify(nome)

    if Pipeline.objects.filter(empresa=tenant, slug=slug).exists():
        return JsonResponse({'error': 'Pipeline já existe'}, status=400)

    pipeline = Pipeline.objects.create(
        empresa=tenant,
        nome=nome,
        slug=slug,
    )

    # Etapas padrão
    etapas_padrao = data.get('etapas', [
        {'nome': 'Novo', 'cor': '#2196F3'},
        {'nome': 'Conversando', 'cor': '#FF9800'},
        {'nome': 'Proposta', 'cor': '#9C27B0'},
        {'nome': 'Negociando', 'cor': '#F44336'},
        {'nome': 'Fechado', 'cor': '#4CAF50', 'is_final': True},
        {'nome': 'Perdido', 'cor': '#607D8B', 'is_final': True},
    ])

    for i, etapa_data in enumerate(etapas_padrao):
        PipelineEtapa.objects.create(
            pipeline=pipeline,
            nome=etapa_data['nome'],
            slug=slugify(etapa_data['nome']),
            cor=etapa_data.get('cor', '#2196F3'),
            ordem=i,
            is_final=etapa_data.get('is_final', False),
        )

    return JsonResponse({
        'status': 'created',
        'pipeline': {
            'id': pipeline.id,
            'nome': pipeline.nome,
            'slug': pipeline.slug,
        }
    }, status=201)


@login_required
def crm_contato_detalhe(request, contato_id):
    """Retorna detalhes de um contato (JSON)."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return JsonResponse({'error': 'Sem empresa'}, status=400)

    contato = get_object_or_404(ContatoPipeline, id=contato_id, empresa=tenant)

    return JsonResponse({
        'id': contato.id,
        'nome': contato.nome,
        'telefone': contato.telefone,
        'email': contato.email,
        'empresa_contato': contato.empresa_contato,
        'prioridade': contato.prioridade,
        'responsavel': contato.responsavel,
        'notas': contato.notas,
        'valor_estimado': str(contato.valor_estimado) if contato.valor_estimado else '',
        'proximo_contato': contato.proximo_contato.isoformat() if contato.proximo_contato else '',
        'origem': contato.origem,
        'tags': contato.tags,
        'pipeline': contato.pipeline.nome,
        'etapa': contato.etapa.nome if contato.etapa else None,
        'etapa_id': contato.etapa_id,
        'created_at': contato.created_at.strftime('%d/%m/%Y %H:%M'),
        'updated_at': contato.updated_at.strftime('%d/%m/%Y %H:%M'),
    })
