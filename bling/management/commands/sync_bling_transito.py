"""
Management command para sincronizar pedidos do Bling por status.

Uso:
    python manage.py sync_bling_transito
    python manage.py sync_bling_transito --empresa=tarragona
    python manage.py sync_bling_transito --empresa=tarragona --dry-run
    python manage.py sync_bling_transito --empresa=tarragona --status=embalado --dry-run
    python manage.py sync_bling_transito --list-situacoes --empresa=tarragona
"""
from django.core.management.base import BaseCommand

from tenants.models import Empresa
from bling.tasks import sync_empresa_pedidos_por_status, BLING_STATUS_MAP


class Command(BaseCommand):
    help = 'Sincroniza pedidos do Bling por status e envia WhatsApp'

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
            '--status', type=str,
            help=f'Status específico para sincronizar ({", ".join(BLING_STATUS_MAP.keys())}). Se omitido, processa todos configurados.'
        )
        parser.add_argument(
            '--list-situacoes', action='store_true',
            help='Lista situações de venda do Bling (para descobrir IDs)'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        empresa_slug = options.get('empresa')
        status_filter = options.get('status')

        if options['list_situacoes']:
            self._list_situacoes(empresa_slug)
            return

        # Validar status se fornecido
        if status_filter and status_filter not in BLING_STATUS_MAP:
            self.stderr.write(
                f"Status '{status_filter}' inválido. "
                f"Opções: {', '.join(BLING_STATUS_MAP.keys())}"
            )
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
            )

        if not empresas.exists():
            self.stdout.write("Nenhuma empresa com Bling configurado encontrada")
            return

        if dry_run:
            self.stdout.write(self.style.WARNING("=== MODO DRY-RUN (nenhuma mensagem será enviada) ==="))

        # Determinar quais status processar
        if status_filter:
            statuses = [status_filter]
        else:
            statuses = list(BLING_STATUS_MAP.keys())

        for empresa in empresas:
            self.stdout.write(f"\nProcessando: {empresa.nome}")
            self.stdout.write(f"  Bling Client ID: {empresa.bling_client_id[:20]}...")

            # Mostrar quais status estão configurados
            configurados = []
            for s, config in BLING_STATUS_MAP.items():
                sit_id = getattr(empresa, config['campo_situacao'], '')
                if sit_id:
                    configurados.append(f"{s} (ID: {sit_id})")
            self.stdout.write(f"  Status configurados: {', '.join(configurados) or 'Nenhum'}")

            for status in statuses:
                config = BLING_STATUS_MAP[status]
                sit_id = getattr(empresa, config['campo_situacao'], '')
                if not sit_id:
                    if status_filter:
                        self.stdout.write(self.style.WARNING(
                            f"  [{status}] Situação não configurada (campo {config['campo_situacao']} vazio)"
                        ))
                    continue

                try:
                    stats = sync_empresa_pedidos_por_status(empresa, status, dry_run=dry_run)
                    self.stdout.write(self.style.SUCCESS(
                        f"  [{status}] {stats['total']} total, "
                        f"{stats['enviados']} enviados, "
                        f"{stats['ja_enviados']} já enviados, "
                        f"{stats['erros']} erros, "
                        f"{stats['sem_telefone']} sem telefone"
                    ))
                except Exception as e:
                    self.stderr.write(self.style.ERROR(f"  [{status}] Erro: {e}"))

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

            # Mostrar mapeamento atual
            self.stdout.write(f"\nMapeamento atual:")
            for status, config in BLING_STATUS_MAP.items():
                sit_id = getattr(empresa, config['campo_situacao'], '') or '(não configurado)'
                self.stdout.write(f"  {status}: {sit_id}")
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Erro: {e}"))
