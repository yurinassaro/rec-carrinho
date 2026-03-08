"""
Tasks Celery para envio diario de mensagens WhatsApp via Meta API.
- Leads do dia anterior (segmentados: cliente vs nao-cliente)
- Carrinhos abandonados do dia anterior
"""
import logging
from celery import shared_task
from datetime import timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name='customers.enviar_promocoes_diarias')
def enviar_promocoes_diarias():
    """
    Task diaria: envia templates Meta para leads e carrinhos do dia anterior.
    Roda via Celery Beat (ex: todo dia as 10h).
    """
    from tenants.models import Empresa

    empresas = Empresa.objects.filter(ativo=True)
    total_leads = 0
    total_carts = 0
    total_inativos = 0

    for empresa in empresas:
        # Verificar se Meta esta configurado
        if not empresa.meta_phone_number_id or not empresa.meta_access_token:
            logger.info(f"[{empresa.slug}] Meta WhatsApp nao configurado, pulando")
            continue

        leads_enviados = _processar_leads_dia_anterior(empresa)
        carts_enviados = _processar_carts_dia_anterior(empresa)
        inativos_enviados = _processar_clientes_inativos(empresa)

        total_leads += leads_enviados
        total_carts += carts_enviados
        total_inativos += inativos_enviados

        if leads_enviados or carts_enviados or inativos_enviados:
            logger.info(
                f"[{empresa.slug}] Promocoes: {leads_enviados} leads, "
                f"{carts_enviados} carrinhos, {inativos_enviados} inativos"
            )

    logger.info(
        f"Promocoes diarias finalizadas: {total_leads} leads, "
        f"{total_carts} carrinhos, {total_inativos} clientes inativos"
    )
    return {'leads': total_leads, 'carts': total_carts, 'inativos': total_inativos}


def _processar_leads_dia_anterior(empresa):
    """
    Processa leads do dia anterior que ainda nao receberam mensagem.
    Segmenta: lead ja cliente vs lead nao cliente (nunca comprou).
    """
    from customers.models import Lead
    from customers.services.meta_promocoes import enviar_meta_lead

    ontem_inicio = timezone.now().replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=1)
    ontem_fim = ontem_inicio + timedelta(days=1)

    leads = Lead.objects.filter(
        empresa=empresa,
        created_at__gte=ontem_inicio,
        created_at__lt=ontem_fim,
        whatsapp_sent=False,
    ).exclude(whatsapp='').exclude(whatsapp__isnull=True)

    enviados = 0
    for lead in leads:
        # Verificar/atualizar se eh cliente
        lead.check_if_customer()

        # Escolher template baseado na segmentacao
        if lead.is_customer:
            if not empresa.meta_template_lead_cliente:
                continue
        else:
            if not empresa.meta_template_lead_nao_cliente:
                continue

        resultado = enviar_meta_lead(lead, empresa)
        if resultado.get('success'):
            enviados += 1

    return enviados


def _processar_carts_dia_anterior(empresa):
    """
    Processa carrinhos abandonados do dia anterior.
    So envia para carrinhos que:
    - Status = abandoned
    - Ainda nao receberam WhatsApp de recuperacao
    - Cliente tem telefone
    """
    from customers.models import Cart
    from customers.services.meta_promocoes import enviar_meta_cart

    ontem_inicio = timezone.now().replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=1)
    ontem_fim = ontem_inicio + timedelta(days=1)

    carts = Cart.objects.filter(
        empresa=empresa,
        status='abandoned',
        recovery_whatsapp_sent=False,
        created_at__gte=ontem_inicio,
        created_at__lt=ontem_fim,
    ).select_related('customer')

    enviados = 0
    for cart in carts:
        if not cart.customer.phone:
            continue

        resultado = enviar_meta_cart(cart, empresa)
        if resultado.get('success'):
            enviados += 1

    return enviados


def _processar_clientes_inativos(empresa):
    """
    Processa clientes inativos (nao compram ha mais de 90 dias).
    Envia cupom de reativacao via Meta template.
    So envia 1 vez - verifica no historico de mensagens.
    Limite: 20 clientes por dia por empresa (evitar spam).
    """
    from customers.models import Customer, MensagemWhatsApp
    from customers.services.meta_promocoes import enviar_meta_cliente_inativo

    if not empresa.meta_template_cliente_inativo:
        return 0

    # Clientes inativos: compraram antes mas nao compram ha 90+ dias
    clientes_inativos = Customer.objects.filter(
        empresa=empresa,
        status__in=['inactive', 'returning', 'first_time'],
        completed_orders__gte=1,
        days_since_last_purchase__gte=90,
        phone__isnull=False,
    ).exclude(phone='')

    # Excluir quem ja recebeu mensagem de reativacao
    ja_enviados = MensagemWhatsApp.objects.filter(
        empresa=empresa,
        tipo='cliente_inativo',
        status='enviado',
    ).values_list('customer_id', flat=True)

    clientes_inativos = clientes_inativos.exclude(id__in=ja_enviados)[:20]

    enviados = 0
    for customer in clientes_inativos:
        resultado = enviar_meta_cliente_inativo(customer, empresa)
        if resultado.get('success'):
            enviados += 1

    return enviados
