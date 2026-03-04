"""
Management command para sincronizar pedidos em trânsito do Bling.

Uso:
    python manage.py sync_bling_transito
    python manage.py sync_bling_transito --empresa=tarragona
    python manage.py sync_bling_transito --empresa=tarragona --dry-run
    python manage.py sync_bling_transito --list-situacoes --empresa=tarragona
"""
from django.core.management.base import BaseCommand

from tenants.models import Empresa
from bling.tasks import sync_empresa_pedidos_transito


class Command(BaseCommand):
    help = 'Sincroniza pedidos em trânsito do Bling e envia WhatsApp'

    def add_arguments(self, parser):
        parser.add_argument(
            '--empresa', type=str,
            help='Slug da empresa (se omitido, processa todas ativas)'
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Simula sem enviar mensagens'
        )
        parser.add_argument(
            '--list-situacoes', action='store_true',
            help='Lista situações de venda do Bling (para descobrir IDs)'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        empresa_slug = options.get('empresa')

        if options['list_situacoes']:
            self._list_situacoes(empresa_slug)
            return

        if empresa_slug:
            empresas = Empresa.objects.filter(slug=empresa_slug)
            if not empresas.exists():
                self.stderr.write(f"Empresa '{empresa_slug}' não encontrada")
                return
        else:
            empresas = Empresa.objects.filter(
                ativo=True,
                bling_client_id__gt='',
                bling_situacao_transito_id__gt='',
            )

        if not empresas.exists():
            self.stdout.write("Nenhuma empresa com Bling configurado encontrada")
            return

        if dry_run:
            self.stdout.write(self.style.WARNING("=== MODO DRY-RUN (nenhuma mensagem será enviada) ==="))

        for empresa in empresas:
            self.stdout.write(f"\nProcessando: {empresa.nome}")
            self.stdout.write(f"  Bling Client ID: {empresa.bling_client_id[:20]}...")
            self.stdout.write(f"  Situação trânsito ID: {empresa.bling_situacao_transito_id}")

            meta_ok = bool(empresa.meta_phone_number_id and empresa.meta_access_token)
            self.stdout.write(f"  Meta WhatsApp: {'Configurado' if meta_ok else 'Não (usará W-API)'}")

            try:
                stats = sync_empresa_pedidos_transito(empresa, dry_run=dry_run)
                self.stdout.write(self.style.SUCCESS(
                    f"  Resultado: {stats['total']} total, "
                    f"{stats['enviados']} enviados, "
                    f"{stats['ja_enviados']} já enviados, "
                    f"{stats['erros']} erros, "
                    f"{stats['sem_telefone']} sem telefone"
                ))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"  Erro: {e}"))

    def _list_situacoes(self, empresa_slug):
        """Lista situações de venda do Bling."""
        if not empresa_slug:
            self.stderr.write("Use --empresa=slug junto com --list-situacoes")
            return

        empresa = Empresa.objects.filter(slug=empresa_slug).first()
        if not empresa:
            self.stderr.write(f"Empresa '{empresa_slug}' não encontrada")
            return

        from bling.services import BlingClient
        client = BlingClient(empresa)

        try:
            situacoes = client.get_situacoes()
            self.stdout.write(f"\nSituações de venda - {empresa.nome}:")
            for s in situacoes:
                self.stdout.write(f"  ID: {s.get('id')}  Nome: {s.get('nome')}")
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Erro: {e}"))
