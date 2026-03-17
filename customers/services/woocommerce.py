"""
Servico de sincronizacao com WooCommerce REST API.
Puxa clientes e pedidos para o banco local (PostgreSQL).
"""
import logging
from decimal import Decimal
from datetime import datetime

from django.utils import timezone
from woocommerce import API

from customers.models import Customer, Order, Cart

logger = logging.getLogger(__name__)


def get_woo_client(empresa):
    """Retorna cliente WooCommerce API configurado."""
    if not empresa.has_woocommerce_api:
        raise ValueError(f"WooCommerce API nao configurado para {empresa.nome}")

    return API(
        url=empresa.woo_store_url,
        consumer_key=empresa.woo_consumer_key,
        consumer_secret=empresa.woo_consumer_secret,
        version="wc/v3",
        timeout=30,
    )


def sync_customers(empresa, page=1, per_page=100):
    """
    Sincroniza clientes do WooCommerce para o banco local.
    Retorna dict com stats.
    """
    wcapi = get_woo_client(empresa)
    criados = 0
    atualizados = 0
    total = 0

    while True:
        response = wcapi.get("customers", params={
            "page": page,
            "per_page": per_page,
            "orderby": "registered_date",
            "order": "desc",
        })

        if response.status_code != 200:
            logger.error(f"[{empresa.slug}] Erro WooCommerce API customers: {response.status_code}")
            break

        customers_data = response.json()
        if not customers_data:
            break

        for wc_customer in customers_data:
            total += 1
            was_created = _upsert_customer(empresa, wc_customer)
            if was_created:
                criados += 1
            else:
                atualizados += 1

        # Verificar se ha mais paginas
        total_pages = int(response.headers.get('X-WP-TotalPages', 1))
        if page >= total_pages:
            break
        page += 1

    logger.info(
        f"[{empresa.slug}] Sync customers: {total} processados, "
        f"{criados} criados, {atualizados} atualizados"
    )
    return {'total': total, 'criados': criados, 'atualizados': atualizados}


def sync_orders(empresa, days_back=7, page=1, per_page=100):
    """
    Sincroniza pedidos do WooCommerce para o banco local.
    Por padrao puxa ultimos 7 dias. Na primeira vez, usar days_back maior.
    """
    wcapi = get_woo_client(empresa)
    criados = 0
    atualizados = 0
    total = 0

    after_date = (timezone.now() - timezone.timedelta(days=days_back)).strftime('%Y-%m-%dT00:00:00')

    while True:
        response = wcapi.get("orders", params={
            "page": page,
            "per_page": per_page,
            "after": after_date,
            "orderby": "date",
            "order": "desc",
        })

        if response.status_code != 200:
            logger.error(f"[{empresa.slug}] Erro WooCommerce API orders: {response.status_code}")
            break

        orders_data = response.json()
        if not orders_data:
            break

        for wc_order in orders_data:
            total += 1
            was_created = _upsert_order(empresa, wc_order)
            if was_created:
                criados += 1
            else:
                atualizados += 1

        total_pages = int(response.headers.get('X-WP-TotalPages', 1))
        if page >= total_pages:
            break
        page += 1

    logger.info(
        f"[{empresa.slug}] Sync orders: {total} processados, "
        f"{criados} criados, {atualizados} atualizados"
    )
    return {'total': total, 'criados': criados, 'atualizados': atualizados}


def _upsert_customer(empresa, wc_data):
    """
    Cria ou atualiza Customer a partir dos dados da API WooCommerce.
    Retorna True se criou, False se atualizou.
    """
    email = (wc_data.get('email') or '').strip().lower()
    if not email:
        return False

    billing = wc_data.get('billing', {})
    phone = billing.get('phone', '') or ''

    # Tentar primeiro nome do billing, fallback para dados do customer
    first_name = (billing.get('first_name') or wc_data.get('first_name') or '').strip()
    last_name = (billing.get('last_name') or wc_data.get('last_name') or '').strip()

    customer, created = Customer.objects.update_or_create(
        empresa=empresa,
        email=email,
        defaults={
            'first_name': first_name or None,
            'last_name': last_name or None,
            'phone': phone or None,
            'billing_address': billing.get('address_1', '') or None,
            'billing_city': billing.get('city', '') or None,
            'billing_state': billing.get('state', '') or None,
            'billing_postcode': billing.get('postcode', '') or None,
        }
    )

    return created


def _upsert_order(empresa, wc_data):
    """
    Cria ou atualiza Order a partir dos dados da API WooCommerce.
    Tambem cria/atualiza o Customer associado e recalcula estatisticas.
    Retorna True se criou, False se atualizou.
    """
    order_id = str(wc_data.get('id', ''))
    if not order_id:
        return False

    # Garantir que o customer existe
    billing = wc_data.get('billing', {})
    email = (billing.get('email') or '').strip().lower()
    if not email:
        return False

    customer, _ = Customer.objects.get_or_create(
        empresa=empresa,
        email=email,
        defaults={
            'first_name': (billing.get('first_name') or '').strip() or None,
            'last_name': (billing.get('last_name') or '').strip() or None,
            'phone': billing.get('phone', '') or None,
            'billing_address': billing.get('address_1', '') or None,
            'billing_city': billing.get('city', '') or None,
            'billing_state': billing.get('state', '') or None,
            'billing_postcode': billing.get('postcode', '') or None,
        }
    )

    # Atualizar dados do customer se vieram vazios antes
    updated_fields = []
    if not customer.phone and billing.get('phone'):
        customer.phone = billing['phone']
        updated_fields.append('phone')
    if not customer.first_name and billing.get('first_name'):
        customer.first_name = billing['first_name'].strip()
        updated_fields.append('first_name')
    if not customer.last_name and billing.get('last_name'):
        customer.last_name = billing['last_name'].strip()
        updated_fields.append('last_name')
    if not customer.billing_city and billing.get('city'):
        customer.billing_city = billing['city']
        updated_fields.append('billing_city')
    if not customer.billing_state and billing.get('state'):
        customer.billing_state = billing['state']
        updated_fields.append('billing_state')
    if updated_fields:
        customer.save(update_fields=updated_fields)

    # Parsear datas
    created_at = _parse_woo_date(wc_data.get('date_created', ''))
    completed_at = _parse_woo_date(wc_data.get('date_completed', ''))

    total = Decimal(str(wc_data.get('total', '0') or '0'))
    status = wc_data.get('status', '')
    items_count = len(wc_data.get('line_items', []))
    payment_method = wc_data.get('payment_method', '') or ''

    order, created = Order.objects.update_or_create(
        empresa=empresa,
        order_id=order_id,
        defaults={
            'customer': customer,
            'order_number': str(wc_data.get('number', order_id)),
            'total': total,
            'status': status,
            'created_at': created_at or timezone.now(),
            'completed_at': completed_at,
            'items_count': items_count,
            'payment_method': payment_method[:100],
        }
    )

    # Recalcular estatisticas do customer
    _recalcular_stats_customer(customer)

    return created


def _recalcular_stats_customer(customer):
    """Recalcula estatisticas de compra do customer baseado nos pedidos locais."""
    from django.db.models import Sum, Count, Min, Max

    orders = Order.objects.filter(customer=customer)

    stats = orders.aggregate(
        total_orders=Count('id'),
        total_spent=Sum('total'),
        first_purchase=Min('created_at'),
        last_purchase=Max('created_at'),
    )

    completed = orders.filter(status__in=['completed', 'wc-completed']).aggregate(
        completed_orders=Count('id'),
    )

    customer.total_orders = stats['total_orders'] or 0
    customer.completed_orders = completed['completed_orders'] or 0
    customer.total_spent = stats['total_spent'] or Decimal('0')
    customer.first_purchase = stats['first_purchase']
    customer.last_purchase = stats['last_purchase']

    if customer.total_orders > 0:
        customer.average_order_value = customer.total_spent / customer.total_orders

    if customer.last_purchase:
        customer.days_since_last_purchase = (timezone.now() - customer.last_purchase).days

    customer.last_activity = timezone.now()
    customer.last_analyzed = timezone.now()

    # Reconciliar carrinhos abandonados:
    # Se o cliente comprou, marcar carrinhos abandonados como convertidos
    if customer.completed_orders > 0:
        _reconciliar_carrinhos(customer)

    # save() vai recalcular status e score automaticamente
    customer.save()


def _reconciliar_carrinhos(customer):
    """
    Marca carrinhos abandonados como convertidos quando o cliente fez uma compra.
    Vincula ao pedido mais proximo (por data) ao carrinho abandonado.
    """
    carrinhos_abandonados = Cart.objects.filter(
        customer=customer,
        status__in=['abandoned', 'active'],
        was_recovered=False,
    )

    if not carrinhos_abandonados.exists():
        return

    # Buscar pedidos completos do cliente
    pedidos = Order.objects.filter(
        customer=customer,
        status__in=['completed', 'wc-completed', 'processing', 'wc-processing'],
    ).order_by('created_at')

    if not pedidos.exists():
        return

    carrinhos_convertidos = 0

    for carrinho in carrinhos_abandonados:
        # Buscar o primeiro pedido feito DEPOIS do carrinho ser criado
        pedido_posterior = pedidos.filter(
            created_at__gte=carrinho.created_at
        ).first()

        if pedido_posterior:
            carrinho.status = 'converted'
            carrinho.was_recovered = True
            carrinho.recovered_order = pedido_posterior
            carrinho.recovered_at = pedido_posterior.created_at
            carrinho.recovery_value = pedido_posterior.total
            carrinho.save()
            carrinhos_convertidos += 1

    if carrinhos_convertidos > 0:
        # Atualizar stats de carrinho no customer
        customer.recovered_carts = Cart.objects.filter(
            customer=customer,
            was_recovered=True,
        ).count()
        customer.abandoned_carts = Cart.objects.filter(
            customer=customer,
            status='abandoned',
            was_recovered=False,
        ).count()

        logger.info(
            f"[{customer.empresa.slug}] {customer.email}: "
            f"{carrinhos_convertidos} carrinhos marcados como convertidos"
        )


def _parse_woo_date(date_str):
    """Parseia data do WooCommerce (ISO 8601)."""
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt)
        return dt
    except (ValueError, TypeError):
        return None
