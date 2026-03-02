from celery import shared_task
from django.core.management import call_command


@shared_task(name='marketing.generate_marketing_lists')
def generate_marketing_lists_task(empresa_slug=None, fmt='csv'):
    """
    Gera listas de marketing para todas as empresas (ou uma especifica).
    Agendar via Celery Beat: todo dia as 6h, por exemplo.
    """
    kwargs = {'format': fmt}
    if empresa_slug:
        kwargs['empresa'] = empresa_slug

    call_command('generate_marketing_lists', **kwargs)
