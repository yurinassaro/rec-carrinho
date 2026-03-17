"""
API para receber leads de atacado do formulário posvendafacil.com.br
e ações de WhatsApp (wapi + meta)
"""
import json
import logging
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
from .models import LeadAtacado, MensagemWhatsApp

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def receber_lead_atacado(request, empresa_slug):
    """
    Recebe lead de atacado do formulário do trocafacil.
    POST /api/v1/leads/atacado/<empresa_slug>/
    """
    try:
        from tenants.models import Empresa
        empresa = Empresa.objects.filter(slug=empresa_slug).first()
        if not empresa:
            return JsonResponse({'error': 'Empresa não encontrada'}, status=404)

        data = json.loads(request.body)

        # Verifica duplicata por WhatsApp + empresa (últimas 24h)
        whatsapp = data.get('whatsapp', '')
        recente = LeadAtacado.objects.filter(
            empresa=empresa,
            whatsapp=whatsapp,
            created_at__gte=timezone.now() - timezone.timedelta(hours=24)
        ).exists()

        if recente:
            return JsonResponse({'status': 'duplicate', 'message': 'Lead já cadastrado recentemente'}, status=200)

        lead = LeadAtacado.objects.create(
            empresa=empresa,
            nome_completo=data.get('nome_completo', ''),
            cpf=data.get('cpf', ''),
            email=data.get('email', ''),
            whatsapp=whatsapp,
            cidade=data.get('cidade', ''),
            estado=data.get('estado', ''),
            status_empresa=data.get('status_empresa', ''),
            nome_empresa=data.get('nome_empresa', ''),
            cnpj=data.get('cnpj', ''),
            nicho_empresarial=data.get('nicho_empresarial', ''),
            instagram=data.get('instagram', ''),
            site_vendas=data.get('site_vendas', ''),
            canais_vendas=data.get('canais_vendas', ''),
            sobre_voce=data.get('sobre_voce', ''),
            plano_interesse=data.get('plano_interesse', ''),
            private_label=data.get('private_label', ''),
            origem='formulario',
        )

        logger.info(f'Lead atacado recebido: {lead.nome_completo} ({empresa.slug})')

        return JsonResponse({
            'status': 'ok',
            'lead_id': lead.id,
            'message': 'Lead cadastrado com sucesso'
        }, status=201)

    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)
    except Exception as e:
        logger.error(f'Erro ao receber lead atacado: {e}')
        return JsonResponse({'error': str(e)}, status=500)


def enviar_whatsapp_lead_atacado(lead, mensagem_texto=None, canal='wapi'):
    """
    Envia WhatsApp para lead de atacado via W-API ou Meta Cloud API.
    Registra no histórico centralizado de MensagemWhatsApp.
    """
    from .services.wapi import WAPIClient, _get_wapi_client, formatar_telefone

    empresa = lead.empresa
    telefone = lead.whatsapp_formatted
    nome = lead.primeiro_nome

    if not telefone:
        return {'success': False, 'error': 'Lead sem WhatsApp válido'}

    # Mensagem padrão se não fornecida
    if not mensagem_texto:
        if lead.status_empresa == 'tenho_empresa_vendo_calcados':
            mensagem_texto = (
                f"Olá {nome}, tudo bem? Aqui é da Tarragona Atacado! "
                f"Recebemos seu cadastro e ficamos felizes com seu interesse. "
                f"Vamos conversar sobre as condições especiais para sua loja?"
            )
        elif lead.status_empresa == 'tenho_empresa_nao_vendo_sapatos':
            mensagem_texto = (
                f"Olá {nome}, tudo bem? Aqui é da Tarragona Atacado! "
                f"Recebemos seu cadastro. Que legal que você quer expandir "
                f"seu negócio com calçados! Vamos conversar?"
            )
        elif lead.status_empresa == 'nao_tenho_empresa_vendo_sapatos':
            mensagem_texto = (
                f"Olá {nome}, tudo bem? Aqui é da Tarragona Atacado! "
                f"Recebemos seu cadastro e vimos que você já revende sapatos. "
                f"Podemos te ajudar a crescer ainda mais!"
            )
        else:
            mensagem_texto = (
                f"Olá {nome}, tudo bem? Aqui é da Tarragona Atacado! "
                f"Recebemos seu cadastro e queremos conhecer mais sobre você. "
                f"Vamos conversar?"
            )

    resultado = {'success': False, 'error': 'Canal não configurado'}

    if canal == 'wapi':
        client = _get_wapi_client(empresa, 'lead')
        if client.esta_configurado():
            resultado = client.enviar_mensagem(telefone, mensagem_texto)
        else:
            resultado = {'success': False, 'error': 'W-API não configurado'}

    elif canal == 'meta':
        try:
            from bling.meta_whatsapp import MetaWhatsAppClient
            meta_client = MetaWhatsAppClient(empresa)
            resultado = meta_client.enviar_texto(telefone, mensagem_texto)
        except Exception as e:
            resultado = {'success': False, 'error': str(e)}

    # Registra no histórico
    MensagemWhatsApp.objects.create(
        empresa=empresa,
        tipo='lead',
        canal=canal,
        status='enviado' if resultado.get('success') else 'falha',
        destinatario_nome=lead.nome_completo,
        destinatario_telefone=telefone,
        mensagem_texto=mensagem_texto,
        error_message=resultado.get('error', '') if not resultado.get('success') else '',
        api_response=resultado.get('response', {}) if resultado.get('success') else {},
        meta_message_id=resultado.get('response', {}).get('messages', [{}])[0].get('id', '') if canal == 'meta' and resultado.get('success') else '',
    )

    # Atualiza lead
    lead.whatsapp_tentativas += 1
    if resultado.get('success'):
        lead.whatsapp_enviado = True
        lead.whatsapp_enviado_em = timezone.now()
        lead.whatsapp_status = 'enviado'
        if lead.status == 'novo':
            lead.status = 'contactado'
    else:
        lead.whatsapp_status = 'falha'
        lead.whatsapp_erro = resultado.get('error', '')[:500]

    lead.save()

    return resultado
