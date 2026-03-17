"""
Tasks Celery para:
- Sync diario de clientes e pedidos via WooCommerce REST API
- Envio diario de mensagens WhatsApp via Meta API
"""
import logging
import os
from celery import shared_task
from datetime import timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name='customers.import_ssh_diario')
def import_ssh_diario():
    """
    Import diario via SSH: carrinhos (CartFlows) e leads (Form Vibes).
    Puxa dados dos ultimos 2 dias para garantir que nada escape.
    Roda via Celery Beat (ex: todo dia as 8h30, antes do sync WooCommerce API).
    """
    from django.core.management import call_command
    from tenants.models import Empresa
    from io import StringIO
    from datetime import datetime, timedelta

    end_date = datetime.now()
    start_date = end_date - timedelta(days=2)

    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')

    empresas = Empresa.objects.filter(ativo=True)
    resultado = {'carrinhos': {}, 'leads': {}}

    for empresa in empresas:
        # Verificar se tem config SSH/WooCommerce
        has_ssh = (
            getattr(empresa, 'has_woocommerce_config', False)
            or bool(os.getenv('SSH_HOST'))
        )
        if not has_ssh:
            logger.info(f"[{empresa.slug}] SSH nao configurado, pulando import")
            continue

        # Import carrinhos e pedidos via SSH
        try:
            out = StringIO()
            call_command(
                'import_customers',
                empresa=empresa.slug,
                start_date=start_str,
                end_date=end_str,
                import_type='all',
                stdout=out,
                verbosity=1,
            )
            resultado['carrinhos'][empresa.slug] = 'ok'
            logger.info(f"[{empresa.slug}] Import carrinhos SSH concluido")
        except Exception as e:
            resultado['carrinhos'][empresa.slug] = str(e)
            logger.error(f"[{empresa.slug}] Erro import carrinhos SSH: {e}")

        # Import leads via SSH
        try:
            out = StringIO()
            call_command(
                'import_leads',
                empresa=empresa.slug,
                start_date=start_str,
                end_date=end_str,
                stdout=out,
                verbosity=1,
            )
            resultado['leads'][empresa.slug] = 'ok'
            logger.info(f"[{empresa.slug}] Import leads SSH concluido")
        except Exception as e:
            resultado['leads'][empresa.slug] = str(e)
            logger.error(f"[{empresa.slug}] Erro import leads SSH: {e}")

    logger.info(f"Import SSH diario finalizado: {resultado}")
    return resultado


@shared_task(name='customers.sync_woocommerce_diario')
def sync_woocommerce_diario():
    """
    Sync diario: puxa clientes e pedidos do WooCommerce REST API.
    Roda via Celery Beat (ex: todo dia as 09h, antes das promocoes).
    """
    from tenants.models import Empresa
    from customers.services.woocommerce import sync_customers, sync_orders

    empresas = Empresa.objects.filter(ativo=True)
    resultado_total = {
        'customers': {'total': 0, 'criados': 0, 'atualizados': 0},
        'orders': {'total': 0, 'criados': 0, 'atualizados': 0},
    }

    for empresa in empresas:
        if not empresa.has_woocommerce_api:
            logger.info(f"[{empresa.slug}] WooCommerce API nao configurado, pulando sync")
            continue

        try:
            # Sync clientes (todos)
            stats_customers = sync_customers(empresa)
            for k in ['total', 'criados', 'atualizados']:
                resultado_total['customers'][k] += stats_customers[k]

            # Sync pedidos (ultimos 7 dias)
            stats_orders = sync_orders(empresa, days_back=7)
            for k in ['total', 'criados', 'atualizados']:
                resultado_total['orders'][k] += stats_orders[k]

            logger.info(
                f"[{empresa.slug}] Sync WooCommerce: "
                f"{stats_customers['total']} clientes, {stats_orders['total']} pedidos"
            )
        except Exception as e:
            logger.error(f"[{empresa.slug}] Erro sync WooCommerce: {e}")

    logger.info(
        f"Sync WooCommerce finalizado: "
        f"{resultado_total['customers']['total']} clientes, "
        f"{resultado_total['orders']['total']} pedidos"
    )
    return resultado_total


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
