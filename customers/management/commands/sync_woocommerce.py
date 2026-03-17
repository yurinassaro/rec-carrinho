"""
Management command para sincronizar clientes e pedidos via WooCommerce REST API.

Uso:
    # Sync diario (ultimos 7 dias de pedidos)
    python manage.py sync_woocommerce --empresa=tarragona

    # Sync completo (todos clientes + pedidos dos ultimos 365 dias)
    python manage.py sync_woocommerce --empresa=tarragona --full

    # Sync apenas pedidos dos ultimos 30 dias
    python manage.py sync_woocommerce --empresa=tarragona --days=30 --only=orders

    # Sync apenas clientes
    python manage.py sync_woocommerce --empresa=tarragona --only=customers
"""
from django.core.management.base import BaseCommand
from tenants.models import Empresa
from customers.services.woocommerce import sync_customers, sync_orders


class Command(BaseCommand):
    help = 'Sincroniza clientes e pedidos via WooCommerce REST API'

    def add_arguments(self, parser):
        parser.add_argument('--empresa', type=str, help='Slug da empresa')
        parser.add_argument('--full', action='store_true', help='Sync completo (365 dias de pedidos)')
        parser.add_argument('--days', type=int, default=7, help='Dias de pedidos para sincronizar (default: 7)')
        parser.add_argument('--only', type=str, choices=['customers', 'orders'], help='Sync apenas clientes ou pedidos')

    def handle(self, *args, **options):
        empresa_slug = options.get('empresa')

        if empresa_slug:
            empresas = Empresa.objects.filter(slug=empresa_slug, ativo=True)
            if not empresas.exists():
                self.stderr.write(f'Empresa "{empresa_slug}" nao encontrada ou inativa')
                return
        else:
            empresas = Empresa.objects.filter(ativo=True)

        days = 365 if options['full'] else options['days']
        only = options.get('only')

        for empresa in empresas:
            if not empresa.has_woocommerce_api:
                self.stdout.write(f'[{empresa.slug}] WooCommerce API nao configurado, pulando')
                continue

            self.stdout.write(f'\n[{empresa.slug}] Iniciando sync WooCommerce...')

            if only != 'orders':
                self.stdout.write('  Sincronizando clientes...')
                stats = sync_customers(empresa)
                self.stdout.write(
                    self.style.SUCCESS(
                        f'  Clientes: {stats["total"]} processados, '
                        f'{stats["criados"]} novos, {stats["atualizados"]} atualizados'
                    )
                )

            if only != 'customers':
                self.stdout.write(f'  Sincronizando pedidos (ultimos {days} dias)...')
                stats = sync_orders(empresa, days_back=days)
                self.stdout.write(
                    self.style.SUCCESS(
                        f'  Pedidos: {stats["total"]} processados, '
                        f'{stats["criados"]} novos, {stats["atualizados"]} atualizados'
                    )
                )

        self.stdout.write(self.style.SUCCESS('\nSync finalizado!'))
