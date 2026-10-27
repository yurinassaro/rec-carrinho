"""
Importa as mensagens prontas do WhatsApp Business pro inbox.

Lê o JSON exportado pela extensão (lista de {pergunta, resposta}) e cria as
RespostaRapida da empresa. Reimportar é seguro: casa pelo título e atualiza o
texto em vez de duplicar, então dá pra exportar de novo depois de mexer nas
respostas lá no WhatsApp.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from customers.models import RespostaRapida
from tenants.models import Empresa


class Command(BaseCommand):
    help = 'Importa respostas rápidas de um JSON [{pergunta, resposta}] para uma empresa.'

    def add_arguments(self, parser):
        parser.add_argument('--arquivo', required=True, help='Caminho do JSON exportado.')
        parser.add_argument('--empresa', required=True, help='Slug da empresa (ex: tarragona).')
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Mostra o que seria importado sem gravar.',
        )

    def handle(self, *args, **opts):
        try:
            empresa = Empresa.objects.get(slug=opts['empresa'])
        except Empresa.DoesNotExist:
            raise CommandError(f"Empresa '{opts['empresa']}' não existe.")

        caminho = Path(opts['arquivo'])
        if not caminho.exists():
            raise CommandError(f'Arquivo não encontrado: {caminho}')

        try:
            dados = json.loads(caminho.read_text(encoding='utf-8'))
        except json.JSONDecodeError as e:
            raise CommandError(f'JSON inválido: {e}')

        if isinstance(dados, dict):
            dados = dados.get('respostas') or dados.get('dados') or []
        if not isinstance(dados, list):
            raise CommandError('Esperava uma lista de {pergunta, resposta}.')

        criadas = atualizadas = ignoradas = 0
        for item in dados:
            if not isinstance(item, dict):
                ignoradas += 1
                continue
            titulo = (item.get('pergunta') or item.get('titulo') or '').strip()
            texto = (item.get('resposta') or item.get('texto') or '').strip()
            if not titulo or not texto:
                ignoradas += 1
                continue
            titulo = titulo[:220]

            if opts['dry_run']:
                criadas += 1
                continue

            existente = RespostaRapida.objects.filter(empresa=empresa, titulo=titulo).first()
            if existente:
                if existente.texto != texto:
                    existente.texto = texto
                    existente.save(update_fields=['texto'])
                    atualizadas += 1
                else:
                    ignoradas += 1
            else:
                RespostaRapida.objects.create(empresa=empresa, titulo=titulo, texto=texto)
                criadas += 1

        prefixo = '[dry-run] ' if opts['dry_run'] else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefixo}{empresa.nome}: {criadas} criadas, {atualizadas} atualizadas, '
            f'{ignoradas} sem mudança/inválidas. '
            f'Total na empresa: {RespostaRapida.objects.filter(empresa=empresa).count()}'
        ))
