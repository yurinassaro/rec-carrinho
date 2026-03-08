"""
Tasks Celery do Motor de Réguas.

- processar_fila_envio: a cada 2 minutos, consome a fila
- avaliar_regras_periodicas: a cada hora, avalia réguas baseadas em tempo (inatividade, etc.)
- atualizar_engagement: diário, recalcula scores e stats
"""
import logging
from celery import shared_task
from datetime import timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name='comunicacao.processar_fila_envio')
def processar_fila_envio():
    """Consome a fila de envio. Roda a cada 2 minutos."""
    from comunicacao.services.sender import processar_fila
    return processar_fila(limit=100)


@shared_task(name='comunicacao.avaliar_regras_periodicas')
def avaliar_regras_periodicas():
    """
    Avalia réguas baseadas em tempo (não em evento).
    Ex: clientes inativos 30/60/90 dias, leads sem conversão, etc.
    Roda a cada hora (mas régras controlam horário de envio).
    """
    from tenants.models import Empresa
    from customers.models import Customer, Lead, Cart
    from comunicacao.services.motor import avaliar_regras_para_gatilho
    from comunicacao.models import RegraComunicacao

    empresas = Empresa.objects.filter(ativo=True)
    total_enfileirados = 0

    for empresa in empresas:
        # Verificar se tem alguma régra ativa
        regras_ativas = RegraComunicacao.objects.filter(
            empresa=empresa, ativo=True,
        ).values_list('gatilho', flat=True).distinct()

        if not regras_ativas:
            continue

        # --- Clientes inativos ---
        gatilhos_inatividade = {
            'customer_inactive_30': 30,
            'customer_inactive_60': 60,
            'customer_inactive_90': 90,
        }

        for gatilho, dias in gatilhos_inatividade.items():
            if gatilho not in regras_ativas:
                continue

            clientes = Customer.objects.filter(
                empresa=empresa,
                completed_orders__gte=1,
                days_since_last_purchase__gte=dias,
                phone__isnull=False,
            ).exclude(phone='')[:50]  # Limite por ciclo

            for customer in clientes:
                results = avaliar_regras_para_gatilho(
                    empresa, gatilho, customer=customer,
                )
                total_enfileirados += sum(1 for item, m in results if item)

        # --- Leads sem conversão (form preenchido ontem) ---
        if 'lead_new' in regras_ativas:
            ontem = timezone.now() - timedelta(days=1)
            leads = Lead.objects.filter(
                empresa=empresa,
                created_at__date=ontem.date(),
                whatsapp_sent=False,
            ).exclude(whatsapp='').exclude(whatsapp__isnull=True)

            for lead in leads:
                lead.check_if_customer()
                results = avaliar_regras_para_gatilho(
                    empresa, 'lead_new', lead=lead,
                )
                total_enfileirados += sum(1 for item, m in results if item)

        # --- Carrinhos abandonados ---
        if 'cart_abandoned' in regras_ativas:
            carts = Cart.objects.filter(
                empresa=empresa,
                status='abandoned',
                recovery_whatsapp_sent=False,
            ).select_related('customer').exclude(
                customer__phone=''
            ).exclude(customer__phone__isnull=True)[:50]

            for cart in carts:
                results = avaliar_regras_para_gatilho(
                    empresa, 'cart_abandoned', cart=cart,
                )
                total_enfileirados += sum(1 for item, m in results if item)

    if total_enfileirados:
        logger.info(f"Réguas periódicas: {total_enfileirados} enfileirados")

    return {'enfileirados': total_enfileirados}


@shared_task(name='comunicacao.atualizar_stats_regras')
def atualizar_stats_regras():
    """
    Atualiza estatísticas das régras (entregues, lidos, respondidos).
    Roda diariamente.
    """
    from comunicacao.models import RegraComunicacao, FilaEnvio
    from customers.models import MensagemWhatsApp

    regras = RegraComunicacao.objects.filter(ativo=True)
    for regra in regras:
        msgs_ids = FilaEnvio.objects.filter(
            regra=regra, status='enviado', mensagem__isnull=False,
        ).values_list('mensagem_id', flat=True)

        if not msgs_ids:
            continue

        msgs = MensagemWhatsApp.objects.filter(id__in=msgs_ids)
        regra.total_enviados = msgs.count()
        regra.total_entregues = msgs.filter(status__in=['entregue', 'lido']).count()
        regra.total_lidos = msgs.filter(status='lido').count()
        regra.total_respondidos = msgs.filter(respondido=True).count()
        regra.save(update_fields=[
            'total_enviados', 'total_entregues', 'total_lidos', 'total_respondidos',
        ])

    logger.info(f"Stats atualizadas para {regras.count()} réguas")
