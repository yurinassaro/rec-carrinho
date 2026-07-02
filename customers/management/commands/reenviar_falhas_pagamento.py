"""
Reenvia mensagens Meta que FALHARAM por problema de pagamento/idioma
(incidente 28/06/2026: "Business eligibility payment issue" + #132001).

Coorte: MensagemWhatsApp status='falha' desde --desde, tipos promocionais.
Regras por tipo (dedupe por telefone, mensagem mais recente ganha):
  - lead / lead_cliente → pula quem COMPROU (comprou_local); reenvia via enviar_meta_lead
  - cart               → pula quem COMPROU; reenvia via enviar_meta_cart
  - cliente_inativo    → pula quem comprou DE NOVO desde --desde; reenvia via
                         enviar_meta_cliente_inativo (cliente antigo por definicao)
  - pedido_novo / status de pedido → IGNORADOS (transacional, reenviar nao faz sentido)
Pula tambem quem ja recebeu QUALQUER promo com sucesso depois de --desde.
O frequency cap normal continua valendo dentro das funcoes enviar_meta_*.

Uso:
    python manage.py reenviar_falhas_pagamento --empresa=tarragona --dry-run
    python manage.py reenviar_falhas_pagamento --empresa=tarragona --limit=20
    python manage.py reenviar_falhas_pagamento --empresa=tarragona            # tudo
"""
import time
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from customers.models import MensagemWhatsApp, Order
from customers.services.cupom_cliente import comprou_local, _so_digitos
from customers.services.meta_promocoes import (
    enviar_meta_cart,
    enviar_meta_cliente_inativo,
    enviar_meta_lead,
)
from tenants.models import Empresa

TIPOS_REENVIO = ['lead', 'lead_cliente', 'cart', 'cliente_inativo']
TIPOS_PROMO_OK = TIPOS_REENVIO  # sucesso posterior em qualquer um destes = nao reenvia


class Command(BaseCommand):
    help = 'Reenvia mensagens Meta que falharam no incidente de pagamento (28/06/2026+)'

    def add_arguments(self, parser):
        parser.add_argument('--empresa', required=True, help='slug da empresa')
        parser.add_argument('--desde', default='2026-06-28',
                            help='data inicial das falhas (YYYY-MM-DD)')
        parser.add_argument('--dry-run', action='store_true',
                            help='apenas lista, nao envia')
        parser.add_argument('--limit', type=int, default=0,
                            help='max de envios (0 = sem limite)')
        parser.add_argument('--sleep', type=float, default=0.5,
                            help='pausa entre envios em segundos (default 0.5)')

    def handle(self, *args, **opts):
        try:
            empresa = Empresa.objects.get(slug=opts['empresa'])
        except Empresa.DoesNotExist:
            raise CommandError(f"Empresa '{opts['empresa']}' nao encontrada")
        desde = date.fromisoformat(opts['desde'])
        dry_run = opts['dry_run']
        limit = opts['limit']

        falhas = MensagemWhatsApp.objects.filter(
            empresa=empresa, canal='meta', status='falha',
            created_at__date__gte=desde, tipo__in=TIPOS_REENVIO,
        ).select_related('lead', 'cart', 'cart__customer', 'customer') \
         .order_by('created_at')

        # Dedupe por telefone — a falha mais RECENTE ganha (tem o FK mais atual)
        por_telefone = {}
        for m in falhas.iterator():
            if m.destinatario_telefone:
                por_telefone[m.destinatario_telefone] = m

        # Quem recebeu alguma promo com sucesso depois → fora
        ok_depois = set(MensagemWhatsApp.objects.filter(
            empresa=empresa, canal='meta', tipo__in=TIPOS_PROMO_OK,
            status__in=['enviado', 'entregue', 'lido'],
            created_at__date__gte=desde,
            destinatario_telefone__in=list(por_telefone.keys()),
        ).values_list('destinatario_telefone', flat=True))

        stats = {
            'coorte': len(por_telefone), 'ok_depois': 0, 'comprou': 0,
            'sem_vinculo': 0, 'enviados': 0, 'skips_cap': 0, 'falhas': 0,
        }
        fila = []

        for telefone, m in por_telefone.items():
            if telefone in ok_depois:
                stats['ok_depois'] += 1
                continue

            if m.tipo in ('lead', 'lead_cliente'):
                if not m.lead:
                    stats['sem_vinculo'] += 1
                    continue
                if comprou_local(empresa, telefone=telefone):
                    stats['comprou'] += 1
                    continue
                fila.append(('lead', m, telefone))

            elif m.tipo == 'cart':
                if not m.cart:
                    stats['sem_vinculo'] += 1
                    continue
                if comprou_local(empresa, telefone=telefone):
                    stats['comprou'] += 1
                    continue
                fila.append(('cart', m, telefone))

            elif m.tipo == 'cliente_inativo':
                if not m.customer:
                    stats['sem_vinculo'] += 1
                    continue
                # cliente antigo por definicao — so pula se comprou DE NOVO desde a data
                if self._comprou_desde(empresa, telefone, desde):
                    stats['comprou'] += 1
                    continue
                fila.append(('cliente_inativo', m, telefone))

        self.stdout.write(self.style.NOTICE(
            f"Coorte de falhas desde {desde}: {stats['coorte']} telefones | "
            f"receberam ok depois: {stats['ok_depois']} | "
            f"compraram: {stats['comprou']} | sem vinculo (FK nulo): {stats['sem_vinculo']} | "
            f"FILA DE REENVIO: {len(fila)}"
        ))
        portipo = {}
        for tipo, _, _ in fila:
            portipo[tipo] = portipo.get(tipo, 0) + 1
        self.stdout.write(f'Fila por tipo: {portipo}')

        if dry_run:
            for tipo, m, telefone in fila[:30]:
                nome = (m.destinatario_nome or '?')[:20]
                self.stdout.write(f'[ENVIARIA] {tipo} | {nome} | {telefone[:6]}****')
            if len(fila) > 30:
                self.stdout.write(f'... e mais {len(fila) - 30}')
            self.stdout.write(self.style.SUCCESS('DRY-RUN — nada enviado.'))
            return

        for i, (tipo, m, telefone) in enumerate(fila, 1):
            if limit and stats['enviados'] >= limit:
                self.stdout.write(f'Limite de {limit} atingido.')
                break
            if tipo == 'lead':
                res = enviar_meta_lead(m.lead, empresa)
            elif tipo == 'cart':
                res = enviar_meta_cart(m.cart, empresa)
            else:
                res = enviar_meta_cliente_inativo(m.customer, empresa)

            if res.get('success'):
                stats['enviados'] += 1
                self.stdout.write(f"[{i}/{len(fila)}] ENVIADO {tipo} {telefone[:6]}****")
            elif res.get('skipped'):
                stats['skips_cap'] += 1
            else:
                stats['falhas'] += 1
                self.stdout.write(self.style.WARNING(
                    f"[{i}/{len(fila)}] FALHA {tipo} {telefone[:6]}****: {res.get('error', '')[:80]}"
                ))
            time.sleep(opts['sleep'])

        self.stdout.write(self.style.SUCCESS(
            f"FIM — enviados: {stats['enviados']} | skips (frequency cap): {stats['skips_cap']} | "
            f"falhas: {stats['falhas']}"
        ))

    def _comprou_desde(self, empresa, telefone, desde):
        """Cliente fez pedido NOVO (nao cancelado) desde a data?"""
        from django.db.models import Value
        from django.db.models.functions import Replace

        tel = _so_digitos(telefone)
        if len(tel) < 8:
            return False
        # phone do Customer vem formatado '(61) 98199-8999' → compara por digitos
        expr = Replace('customer__phone', Value('('), Value(''))
        expr = Replace(expr, Value(')'), Value(''))
        expr = Replace(expr, Value(' '), Value(''))
        expr = Replace(expr, Value('-'), Value(''))
        return Order.objects.filter(
            empresa=empresa,
            created_at__date__gte=desde,
        ).exclude(status__in=['cancelled', 'wc-cancelled', 'failed', 'refunded']) \
         .annotate(phone_digits=expr) \
         .filter(phone_digits__endswith=tel[-8:]).exists()
