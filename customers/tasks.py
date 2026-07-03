"""
Tasks Celery para:
- Sync diario de clientes e pedidos via WooCommerce REST API
- Envio diario de mensagens WhatsApp via Meta API
- Monitoramento de status W-API (3x ao dia)
"""
import logging
import os
import requests
from celery import shared_task
from datetime import timedelta
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)


# ---- Cupom cliente (botao do admin, com barra de %) ----

def cupom_cache_key(empresa_id, fase='envio'):
    """Chave de progresso no cache (Redis). fase: 'preview' ou 'envio'."""
    return f'cupom_cliente_{fase}_{empresa_id}'


@shared_task(name='customers.cupom_cliente')
def cupom_cliente_task(empresa_id, alvo='ambos', dry_run=True, limit=0,
                       usar_woo=False, data_inicio=None, data_fim=None):
    """
    Roda em background a verificacao/envio do cupom cliente, atualizando o
    progresso (%) no cache para a barra do admin acompanhar.

    dry_run=True  -> fase 'preview': verifica e CONTA elegiveis, sem enviar.
    dry_run=False -> fase 'envio': verifica e ENVIA o cupom.

    Verificacao "comprou" usa dados LOCAIS por padrao (Customer.completed_orders,
    importados do Woo via SSH). usar_woo=True forca a REST API (fallback).
    data_inicio/data_fim: strings 'YYYY-MM-DD' (opcional).
    """
    from datetime import datetime
    from tenants.models import Empresa
    from customers.services.cupom_cliente import processar_cupom_cliente

    def _parse(valor):
        return datetime.strptime(valor, '%Y-%m-%d').date() if valor else None

    di = _parse(data_inicio)
    df = _parse(data_fim)
    fase = 'preview' if dry_run else 'envio'
    key = cupom_cache_key(empresa_id, fase)
    empresa = Empresa.objects.get(pk=empresa_id)

    wcapi = None
    if usar_woo and empresa.has_woocommerce_api:
        from customers.services.woocommerce import get_woo_client
        wcapi = get_woo_client(empresa)

    cache.set(key, {
        'status': 'running', 'fase': fase, 'done': 0, 'total': 0, 'percent': 0,
        'enviados': 0, 'stats': None, 'iniciado_em': timezone.now().isoformat(),
    }, 3600)

    def progress_cb(done, total, stats):
        percent = int(done * 100 / total) if total else 100
        cache.set(key, {
            'status': 'running', 'fase': fase, 'done': done, 'total': total,
            'percent': percent, 'enviados': stats['enviados'], 'stats': dict(stats),
            'iniciado_em': timezone.now().isoformat(),
        }, 3600)

    try:
        stats = processar_cupom_cliente(
            empresa, alvo=alvo, dry_run=dry_run, limit=limit,
            wcapi=wcapi, progress_cb=progress_cb,
            data_inicio=di, data_fim=df,
        )
        cache.set(key, {
            'status': 'done', 'fase': fase, 'percent': 100,
            'enviados': stats['enviados'], 'stats': dict(stats),
            'elegiveis': stats['carts_enviar'] + stats['leads_enviar'],
            'finalizado_em': timezone.now().isoformat(),
        }, 3600)
        logger.info(f"[{empresa.slug}] Cupom cliente ({fase}): "
                    f"elegiveis={stats['carts_enviar'] + stats['leads_enviar']} enviados={stats['enviados']}")
        return stats
    except Exception as e:
        logger.exception(f"[{empresa.slug}] Erro cupom_cliente_task ({fase})")
        cache.set(key, {'status': 'error', 'fase': fase, 'erro': str(e), 'percent': 0}, 3600)
        raise


@shared_task(name='customers.monitorar_wapi')
def monitorar_wapi():
    """
    Verifica status de todas as instancias W-API ativas e envia
    alerta via WhatsApp para o telefone de monitoramento da empresa.
    Roda 3x ao dia: 08h, 14h, 20h.
    """
    from tenants.models import Empresa, InstanciaWAPI
    from customers.services.wapi import WAPIClient, formatar_telefone

    empresas = Empresa.objects.filter(ativo=True, wapi_ativo=True).exclude(
        wapi_telefone_monitoramento=''
    )

    for empresa in empresas:
        telefone = formatar_telefone(empresa.wapi_telefone_monitoramento)
        if not telefone:
            continue

        # Verificar todas as instancias da empresa
        instancias = InstanciaWAPI.objects.filter(empresa=empresa, ativo=True)
        if not instancias.exists():
            continue

        status_list = []
        todas_ok = True

        for inst in instancias:
            try:
                resp = requests.get(
                    'https://api.w-api.app/v1/instance/status-instance',
                    params={'instanceId': inst.wapi_instance},
                    headers={'Authorization': f'Bearer {inst.wapi_token}'},
                    timeout=15,
                )
                if resp.ok:
                    data = resp.json()
                    connected = data.get('connected', False)
                    status_emoji = 'OK' if connected else 'OFFLINE'
                    if not connected:
                        todas_ok = False
                    status_list.append(f'{inst.nome}: {status_emoji}')
                else:
                    todas_ok = False
                    status_list.append(f'{inst.nome}: ERRO API ({resp.status_code})')
            except Exception as e:
                todas_ok = False
                status_list.append(f'{inst.nome}: ERRO ({str(e)[:30]})')

        # Montar mensagem
        hora = timezone.now().strftime('%H:%M')
        status_geral = 'Tudo OK' if todas_ok else 'ATENCAO - Problemas detectados'
        detalhes = '\n'.join(status_list)
        mensagem = (
            f'[Monitoramento W-API - {hora}]\n'
            f'{empresa.nome}: {status_geral}\n\n'
            f'{detalhes}'
        )

        # Enviar usando a primeira instancia conectada (ou fallback)
        client = WAPIClient(
            token=empresa.wapi_token or None,
            instance=empresa.wapi_instance or None,
        )
        # Tentar usar uma instancia que esteja conectada
        for inst in instancias:
            try:
                resp = requests.get(
                    'https://api.w-api.app/v1/instance/status-instance',
                    params={'instanceId': inst.wapi_instance},
                    headers={'Authorization': f'Bearer {inst.wapi_token}'},
                    timeout=10,
                )
                if resp.ok and resp.json().get('connected'):
                    client = WAPIClient(token=inst.wapi_token, instance=inst.wapi_instance)
                    break
            except Exception:
                continue

        result = client.enviar_mensagem(telefone, mensagem)
        if result.get('success'):
            logger.info(f'[{empresa.slug}] Monitoramento W-API enviado para {telefone}')
        else:
            logger.warning(f'[{empresa.slug}] Falha monitoramento W-API: {result.get("error")}')


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


# ═══════════════════════════════════════════════════════════════════
# Ciclo diario do cupom (19h) — importa, trata quem comprou, envia e
# manda relatorio no WhatsApp do admin.
# ═══════════════════════════════════════════════════════════════════

def _enviar_relatorio_admin(empresa, texto, template_params=None):
    """
    Envia o relatorio pro WhatsApp do admin (CUPOM_RELATORIO_WHATSAPP).
    Cadeia de fallback:
      1. W-API (sem janela 24h; requer assinatura ativa)
      2. Meta texto livre (requer janela 24h aberta — admin respondeu o numero)
      3. Meta template 'relatorio_cupom_diario' (SEMPRE chega; versao compacta)
         params: [data_hora, analisados, enviados, status]
    Retorna 'wapi', 'meta', 'template' ou 'falhou'.
    """
    from customers.services.wapi import _get_wapi_client, formatar_telefone

    telefone = formatar_telefone(os.getenv('CUPOM_RELATORIO_WHATSAPP', '16997553499'))
    if not telefone:
        return 'falhou'

    client = _get_wapi_client(empresa, None)
    if client and client.esta_configurado():
        res = client.enviar_mensagem(telefone, texto)
        if res.get('success'):
            return 'wapi'
        logger.warning(f"Relatorio via W-API falhou: {res.get('error')}")

    try:
        from bling.meta_whatsapp import MetaWhatsAppClient
        meta = MetaWhatsAppClient(
            phone_number_id=empresa.meta_phone_number_id,
            access_token=empresa.meta_access_token,
        )
        # 2. Texto livre (rico) — a API aceita mesmo com janela fechada, mas
        #    a Meta descarta na entrega. Por isso o template (3) tambem vai
        #    quando ha params: garantia de chegada (utility ~R$0,07).
        res_texto = meta.enviar_texto(telefone, texto)
        if not res_texto.get('success'):
            logger.warning(f"Relatorio via Meta texto falhou: {res_texto.get('error')}")

        # 3. Template utility (sempre entrega)
        if template_params:
            from customers.services.meta_promocoes import _detectar_idioma_template
            nome_tpl = 'relatorio_cupom_diario'
            idioma = _detectar_idioma_template(empresa, nome_tpl)
            res_tpl = meta.enviar_template(telefone, nome_tpl, template_params,
                                           language=idioma)
            if res_tpl.get('success'):
                return 'template'
            logger.warning(f"Relatorio via template falhou: {res_tpl.get('error')}")
        if res_texto.get('success'):
            return 'meta'
    except Exception as e:
        logger.error(f"Relatorio Meta exception: {e}")
    return 'falhou'


@shared_task(name='customers.cupom_diario_19h')
def cupom_diario_19h():
    """
    Ciclo diario do cupom (Celery Beat, 19h):
      1. Importa carts + leads + pedidos dos ultimos 2 dias (SSH/Form Vibes)
      2. Trata quem comprou (marca convertido) e ENVIA cupom pra quem nao
         (mesma logica do botao "Verificar e enviar cupom" do admin)
      3. Manda relatorio no WhatsApp do admin (env CUPOM_RELATORIO_WHATSAPP)
    """
    from io import StringIO
    from django.core.management import call_command
    from django.utils import timezone as tz
    from datetime import datetime, timedelta
    from tenants.models import Empresa
    from customers.services.cupom_cliente import processar_cupom_cliente

    end_date = datetime.now()
    start_date = end_date - timedelta(days=2)
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')

    for empresa in Empresa.objects.filter(ativo=True):
        if not (empresa.meta_phone_number_id and empresa.meta_access_token):
            continue

        import_status = {'carts': '—', 'leads': '—'}

        # 1. Import carrinhos + clientes + pedidos (SSH) — pedidos frescos
        #    garantem que o "quem comprou" esteja atualizado.
        try:
            call_command(
                'import_customers', empresa=empresa.slug,
                start_date=start_str, end_date=end_str,
                import_type='all', stdout=StringIO(), verbosity=0,
            )
            import_status['carts'] = 'ok'
        except Exception as e:
            import_status['carts'] = f'ERRO: {str(e)[:60]}'
            logger.error(f"[{empresa.slug}] cupom_diario: erro import carts: {e}")

        # Import leads (Form Vibes)
        try:
            call_command(
                'import_leads', empresa=empresa.slug,
                start_date=start_str, end_date=end_str,
                stdout=StringIO(), verbosity=0,
            )
            import_status['leads'] = 'ok'
        except Exception as e:
            import_status['leads'] = f'ERRO: {str(e)[:60]}'
            logger.error(f"[{empresa.slug}] cupom_diario: erro import leads: {e}")

        # 2 + 3. Verificar compra e enviar cupons (mesma logica do botao)
        erro_envio = ''
        stats = None
        try:
            stats = processar_cupom_cliente(empresa, alvo='ambos', dry_run=False)
        except Exception as e:
            erro_envio = str(e)[:120]
            logger.exception(f"[{empresa.slug}] cupom_diario: erro no envio")

        # 4. Relatorio
        agora = tz.localtime().strftime('%d/%m %H:%M')
        template_params = None
        if stats:
            total_analisado = stats['carts_total'] + stats['leads_total']
            total_enviado = stats['enviados']
            tudo_certo = (import_status['carts'] == 'ok'
                          and import_status['leads'] == 'ok' and not erro_envio)
            template_params = [
                agora, str(total_analisado), str(total_enviado),
                'Tudo certo' if tudo_certo else 'Com erros - ver logs no servidor',
            ]
            texto = (
                f"🌙 *Cupom diario 19h — {empresa.nome}* ({agora})\n\n"
                f"📥 Import: carts {import_status['carts']} | leads {import_status['leads']}\n\n"
                f"🛒 *Carrinhos:* {stats['carts_total']} analisados\n"
                f"   • compraram (poupados): {stats['carts_comprou']}\n"
                f"   • ja tinham msg recente: {stats['carts_ja_msg']}\n"
                f"   • sem telefone: {stats['carts_sem_tel']}\n"
                f"   • ✅ enviados: {stats['carts_enviados']}\n\n"
                f"📋 *Leads:* {stats['leads_total']} analisados\n"
                f"   • compraram (poupados): {stats['leads_comprou']}\n"
                f"   • ja tinham msg recente: {stats['leads_ja_msg']}\n"
                f"   • sem telefone: {stats['leads_sem_tel']}\n"
                f"   • ✅ enviados: {stats['leads_enviados']}\n\n"
                f"📤 *TOTAL ENVIADO: {total_enviado}* de {total_analisado} analisados\n"
                + ("✅ Tudo certo!" if tudo_certo else "⚠️ Teve erro — ver logs no servidor.")
            )
        else:
            texto = (
                f"🌙 *Cupom diario 19h — {empresa.nome}* ({agora})\n\n"
                f"📥 Import: carts {import_status['carts']} | leads {import_status['leads']}\n"
                f"❌ ERRO no envio de cupons: {erro_envio}\n"
                f"Nenhum cupom foi enviado — verificar logs."
            )
            template_params = [agora, '0', '0', 'ERRO no envio - ver logs']

        canal = _enviar_relatorio_admin(empresa, texto, template_params)
        logger.info(f"[{empresa.slug}] cupom_diario_19h: relatorio via {canal}; stats={stats}")

    return 'ok'
