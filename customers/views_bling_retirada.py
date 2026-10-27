"""
Tela "Aguardando Retirada" (Bling - Objetos de postagem).

Lista os objetos de postagem em situação "Aguardando retirada" (código 4 do
rastreamento na API V3 do Bling) e permite disparar WhatsApp manualmente, um a
um, pelo número conectado na W-API.

Versão inicial: disparo manual via botão. Futuramente migrar para API oficial Meta.
"""
import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST

from bling.services import listar_aguardando_retirada
from customers.models import MensagemWhatsApp
from customers.services.wapi import _get_wapi_client, formatar_telefone

logger = logging.getLogger(__name__)

TIPO_MSG = 'pedido_transito'  # tipo usado para resolver a instância W-API


def _montar_mensagem(empresa, item):
    """Renderiza o template de mensagem da empresa com os dados do objeto."""
    template = (
        empresa.msg_whatsapp_aguardando_retirada
        or 'Olá {nome}! Seu pedido #{pedido} está disponível para retirada. '
           'Código: {codigo}. Rastreie em: {link}'
    )
    return template.format(
        nome=(item.get('contato_nome') or '').split(' ')[0] or 'tudo bem',
        pedido=item.get('pedido_numero', ''),
        codigo=item.get('codigo_rastreio', ''),
        link=item.get('rastreio_url', ''),
    )


@login_required
def aguardando_retirada(request):
    """Lista os objetos em 'Aguardando retirada' do Bling."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return redirect('/tenants/select/')

    id_logistica = request.GET.get('logistica') or tenant.bling_logistica_id
    itens = []
    erro = None

    if not tenant.bling_client_id:
        erro = 'Bling não está configurado para esta empresa.'
    elif not id_logistica:
        erro = ('ID da logística não configurado. Defina "ID Logística" no admin da '
                'empresa ou passe ?logistica=<id> na URL.')
    else:
        try:
            itens = listar_aguardando_retirada(tenant, id_logistica)
        except Exception as e:
            logger.exception('Erro ao listar aguardando retirada do Bling')
            erro = f'Erro ao consultar o Bling: {e}'

    # Marca quais já receberam mensagem desse tipo (pelo telefone)
    telefones = {formatar_telefone(i['telefone']) for i in itens if i.get('telefone')}
    ja_enviados = set()
    if telefones:
        ja_enviados = set(
            MensagemWhatsApp.objects.filter(
                empresa=tenant,
                tipo=TIPO_MSG,
                destinatario_telefone__in=telefones,
                status__in=['enviado', 'entregue', 'lido'],
            ).values_list('destinatario_telefone', flat=True)
        )

    for item in itens:
        tel = formatar_telefone(item.get('telefone', ''))
        item['telefone_fmt'] = tel
        item['ja_enviado'] = tel in ja_enviados
        item['preview'] = _montar_mensagem(tenant, item)

    return render(request, 'customers/bling_retirada.html', {
        'empresa': tenant,
        'itens': itens,
        'erro': erro,
        'id_logistica': id_logistica,
    })


@login_required
@require_POST
def aguardando_retirada_enviar(request):
    """Envia WhatsApp (W-API) para um objeto em aguardando retirada."""
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return JsonResponse({'success': False, 'error': 'Sem empresa selecionada.'}, status=400)

    import json
    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        data = request.POST

    telefone = data.get('telefone', '')
    nome = data.get('nome', '')
    pedido = data.get('pedido', '')
    codigo = data.get('codigo', '')
    link = data.get('link', '')

    telefone_fmt = formatar_telefone(telefone)
    if not telefone_fmt:
        return JsonResponse({'success': False, 'error': 'Telefone inválido ou ausente.'}, status=400)

    mensagem = _montar_mensagem(tenant, {
        'contato_nome': nome,
        'pedido_numero': pedido,
        'codigo_rastreio': codigo,
        'rastreio_url': link,
    })

    client = _get_wapi_client(tenant, TIPO_MSG)
    resultado = client.enviar_mensagem(telefone_fmt, mensagem)
    sucesso = resultado.get('success', False)

    MensagemWhatsApp.objects.create(
        empresa=tenant,
        tipo=TIPO_MSG,
        canal='wapi',
        status='enviado' if sucesso else 'falha',
        destinatario_nome=nome or '',
        destinatario_telefone=telefone_fmt,
        mensagem_texto=mensagem,
        error_message='' if sucesso else resultado.get('error', ''),
        api_response=resultado.get('response', {}) if sucesso else {},
    )

    if sucesso:
        return JsonResponse({'success': True})
    return JsonResponse({'success': False, 'error': resultado.get('error', 'Falha ao enviar.')}, status=502)
