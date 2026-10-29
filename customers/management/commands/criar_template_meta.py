"""
Cria um template de mensagem na Meta sem precisar do WhatsApp Manager.

O nome do template é PARA SEMPRE (não dá pra renomear), e a Meta pode recusar
a categoria que você pediu — por isso o comando mostra o JSON e só envia com
--confirmar. Sem a flag, ele só imprime o que mandaria.

    python manage.py criar_template_meta --empresa=tarragona --arquivo=t.json
    python manage.py criar_template_meta --empresa=tarragona --arquivo=t.json --confirmar
"""
import json
from pathlib import Path

import requests
from django.core.management.base import BaseCommand, CommandError

from tenants.models import Empresa

GRAPH = 'https://graph.facebook.com/v21.0'
CATEGORIAS = ('UTILITY', 'MARKETING', 'AUTHENTICATION')


class Command(BaseCommand):
    help = 'Cria um template de mensagem na Meta a partir de um JSON.'

    def add_arguments(self, parser):
        parser.add_argument('--empresa', required=True, help='Slug da empresa (ex: tarragona).')
        parser.add_argument('--arquivo', required=True, help='JSON com name/category/language/components.')
        parser.add_argument(
            '--confirmar', action='store_true',
            help='Sem isso o comando só mostra o que seria enviado.',
        )

    def handle(self, *args, **opts):
        try:
            empresa = Empresa.objects.get(slug=opts['empresa'])
        except Empresa.DoesNotExist:
            raise CommandError(f"Empresa '{opts['empresa']}' não existe.")
        if not empresa.meta_waba_id or not empresa.meta_access_token:
            raise CommandError('Empresa sem WABA ID ou token da Meta.')

        caminho = Path(opts['arquivo'])
        if not caminho.exists():
            raise CommandError(f'Arquivo não encontrado: {caminho}')
        try:
            corpo = json.loads(caminho.read_text(encoding='utf-8'))
        except json.JSONDecodeError as e:
            raise CommandError(f'JSON inválido: {e}')

        for campo in ('name', 'category', 'language', 'components'):
            if not corpo.get(campo):
                raise CommandError(f'Falta "{campo}" no JSON.')
        if corpo['category'].upper() not in CATEGORIAS:
            raise CommandError(f'category deve ser uma de {CATEGORIAS}.')
        corpo['category'] = corpo['category'].upper()

        # Variável sem exemplo a Meta recusa — melhor avisar aqui que depois.
        for c in corpo['components']:
            texto = c.get('text') or ''
            if '{{' in texto and not c.get('example'):
                raise CommandError(
                    f"O componente {c.get('type')} usa variável e não tem 'example'."
                )

        self.stdout.write('Vai ser enviado para a Meta:')
        self.stdout.write(json.dumps(corpo, indent=2, ensure_ascii=False))

        if not opts['confirmar']:
            self.stdout.write(self.style.WARNING(
                '\nNada foi criado. Rode de novo com --confirmar para valer.\n'
                'Lembre: o nome não pode ser alterado depois.'
            ))
            return

        r = requests.post(
            f'{GRAPH}/{empresa.meta_waba_id}/message_templates',
            headers={'Authorization': f'Bearer {empresa.meta_access_token}'},
            json=corpo, timeout=30,
        )
        try:
            resposta = r.json()
        except ValueError:
            raise CommandError(f'Resposta não-JSON da Meta ({r.status_code}): {r.text[:200]}')

        if 'error' in resposta:
            raise CommandError(f"Meta recusou: {resposta['error'].get('message')}")

        self.stdout.write(self.style.SUCCESS(
            f"Criado: id={resposta.get('id')} | situação={resposta.get('status')} | "
            f"categoria={resposta.get('category')}"
        ))
        if (resposta.get('status') or '').upper() == 'REJECTED':
            self.stdout.write(self.style.ERROR(
                'A Meta já criou REJEITADO — quase sempre é categoria errada '
                '(INCORRECT_CATEGORY). Veja o motivo no WhatsApp Manager.'
            ))
        else:
            self.stdout.write(
                'A revisão costuma sair em minutos (o prazo oficial é 24h). '
                'O inbox só lista o que estiver APPROVED.'
            )
