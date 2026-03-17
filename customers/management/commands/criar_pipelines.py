"""
Cria pipelines padrão para uma empresa.
Uso: python manage.py criar_pipelines <slug_empresa>
"""
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from tenants.models import Empresa
from customers.models import Pipeline, PipelineEtapa


PIPELINES_PADRAO = [
    {
        'nome': 'Vendas',
        'etapas': [
            {'nome': 'Novo', 'cor': '#2196F3'},
            {'nome': 'Conversando', 'cor': '#FF9800'},
            {'nome': 'Proposta Enviada', 'cor': '#9C27B0'},
            {'nome': 'Negociando', 'cor': '#F44336'},
            {'nome': 'Fechado Ganho', 'cor': '#4CAF50', 'is_final': True},
            {'nome': 'Perdido', 'cor': '#607D8B', 'is_final': True},
        ],
    },
    {
        'nome': 'Atacado',
        'etapas': [
            {'nome': 'Lead Novo', 'cor': '#2196F3'},
            {'nome': 'Primeiro Contato', 'cor': '#00BCD4'},
            {'nome': 'Interesse', 'cor': '#FF9800'},
            {'nome': 'Catalogo Enviado', 'cor': '#9C27B0'},
            {'nome': 'Pedido Feito', 'cor': '#4CAF50', 'is_final': True},
            {'nome': 'Sem Interesse', 'cor': '#607D8B', 'is_final': True},
        ],
    },
    {
        'nome': 'Pos-Venda',
        'etapas': [
            {'nome': 'Solicitacao', 'cor': '#2196F3'},
            {'nome': 'Em Analise', 'cor': '#FF9800'},
            {'nome': 'Aguardando Cliente', 'cor': '#9C27B0'},
            {'nome': 'Resolvido', 'cor': '#4CAF50', 'is_final': True},
        ],
    },
]


class Command(BaseCommand):
    help = 'Cria pipelines padrão para uma empresa'

    def add_arguments(self, parser):
        parser.add_argument('empresa_slug', type=str, help='Slug da empresa')
        parser.add_argument('--force', action='store_true', help='Recriar mesmo se já existir')

    def handle(self, *args, **options):
        slug = options['empresa_slug']

        try:
            empresa = Empresa.objects.get(slug=slug)
        except Empresa.DoesNotExist:
            self.stderr.write(f'Empresa com slug "{slug}" não encontrada.')
            self.stdout.write('\nEmpresas disponíveis:')
            for e in Empresa.objects.filter(ativo=True):
                self.stdout.write(f'  - {e.slug} ({e.nome})')
            return

        self.stdout.write(f'Empresa: {empresa.nome} ({empresa.slug})')

        for pipeline_data in PIPELINES_PADRAO:
            pipeline_slug = slugify(pipeline_data['nome'])

            if Pipeline.objects.filter(empresa=empresa, slug=pipeline_slug).exists():
                if not options['force']:
                    self.stdout.write(f'  Pipeline "{pipeline_data["nome"]}" já existe. Use --force para recriar.')
                    continue
                Pipeline.objects.filter(empresa=empresa, slug=pipeline_slug).delete()

            pipeline = Pipeline.objects.create(
                empresa=empresa,
                nome=pipeline_data['nome'],
                slug=pipeline_slug,
            )
            self.stdout.write(self.style.SUCCESS(f'  Pipeline criado: {pipeline.nome}'))

            for i, etapa_data in enumerate(pipeline_data['etapas']):
                PipelineEtapa.objects.create(
                    pipeline=pipeline,
                    nome=etapa_data['nome'],
                    slug=slugify(etapa_data['nome']),
                    cor=etapa_data.get('cor', '#2196F3'),
                    ordem=i,
                    is_final=etapa_data.get('is_final', False),
                )
                self.stdout.write(f'    Etapa: {etapa_data["nome"]}')

        self.stdout.write(self.style.SUCCESS('\nPipelines criados com sucesso!'))
        self.stdout.write(f'Acesse o CRM em: /crm/')
