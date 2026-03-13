"""
Gera a API key para a extensão Chrome de uma empresa.
Uso: python manage.py generate_api_key <slug>
"""
import hashlib
from django.core.management.base import BaseCommand
from tenants.models import Empresa


class Command(BaseCommand):
    help = 'Gera a API key da extensão Chrome para uma empresa'

    def add_arguments(self, parser):
        parser.add_argument('slug', type=str, help='Slug da empresa')

    def handle(self, *args, **options):
        slug = options['slug']

        try:
            empresa = Empresa.objects.get(slug=slug)
        except Empresa.DoesNotExist:
            self.stderr.write(self.style.ERROR(f'Empresa "{slug}" não encontrada'))
            return

        if not empresa.woo_webhook_secret:
            self.stderr.write(self.style.ERROR(
                f'Empresa "{slug}" não tem woo_webhook_secret configurado. '
                'Configure no admin antes de gerar a key.'
            ))
            return

        api_key = hashlib.sha256(
            f"{empresa.slug}:{empresa.woo_webhook_secret}".encode()
        ).hexdigest()[:32]

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'API Key para "{empresa.nome}":'))
        self.stdout.write('')
        self.stdout.write(f'  {api_key}')
        self.stdout.write('')
        self.stdout.write(f'Use essa key na extensão Chrome.')
        self.stdout.write(f'URL do CRM: http://143.110.150.237:9011')
        self.stdout.write(f'Slug: {empresa.slug}')
