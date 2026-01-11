# importer/tasks.py
from celery import shared_task
from django.core.cache import cache
from django.core.management import call_command
from io import StringIO
import logging
import traceback

logger = logging.getLogger(__name__)


class ProgressWriter:
    """Wrapper que captura output e atualiza progresso no cache"""
    def __init__(self, task_id):
        self.task_id = task_id
        self.buffer = StringIO()
        self.progress = 5
        # Contadores para resumo final
        self.stats = {
            'carrinhos_total': 0,
            'carrinhos_sucesso': 0,
            'pedidos_total': 0,
            'clientes_atualizados': 0,
            'recuperados': 0,
            'abandonados': 0,
        }

    def write(self, msg):
        self.buffer.write(msg)

        # Capturar estatísticas das mensagens
        import re

        # Capturar total de carrinhos encontrados
        match = re.search(r'Encontrados (\d+) carrinhos', msg)
        if match:
            self.stats['carrinhos_total'] = int(match.group(1))
            self._update(20, f'Encontrados {self.stats["carrinhos_total"]} carrinhos...')
            return

        # Capturar carrinhos processados com sucesso
        match = re.search(r'Sucesso: (\d+)', msg)
        if match:
            self.stats['carrinhos_sucesso'] = int(match.group(1))

        # Capturar pedidos processados
        match = re.search(r'Processando (\d+) pedidos', msg)
        if match:
            self.stats['pedidos_total'] = int(match.group(1))
            self._update(75, f'Processando {self.stats["pedidos_total"]} pedidos...')
            return

        # Capturar pedidos importados
        match = re.search(r'(\d+) pedidos importados', msg)
        if match:
            self.stats['pedidos_total'] = int(match.group(1))

        # Capturar clientes atualizados
        match = re.search(r'(\d+) clientes atualizados', msg)
        if match:
            self.stats['clientes_atualizados'] += int(match.group(1))

        # Capturar recuperados
        match = re.search(r'Recuperados: (\d+)', msg)
        if match:
            self.stats['recuperados'] = int(match.group(1))

        # Capturar abandonados definitivos
        match = re.search(r'Abandonados definitivos: (\d+)', msg)
        if match:
            self.stats['abandonados'] = int(match.group(1))

        # Atualizar progresso baseado nas mensagens
        if 'Conectando' in msg or 'Conexão' in msg or 'conectado' in msg.lower():
            self._update(10, 'Conectando ao banco de dados...')
        elif 'Processando' in msg and 'carrinhos' in msg:
            self._update(30, 'Processando carrinhos...')
        elif 'Novo carrinho' in msg or 'Atualizado' in msg:
            # Incrementar progresso gradualmente
            if self.progress < 70:
                self.progress += 1
                self._update(self.progress, 'Importando dados...')
        elif 'análise' in msg.lower() or 'Analis' in msg:
            self._update(85, 'Executando análise...')
        elif 'Verificando recuperação' in msg:
            self._update(90, 'Verificando recuperações...')
        elif 'Resumo' in msg or 'concluíd' in msg.lower():
            self._update(95, 'Finalizando...')

    def _update(self, progress, message):
        self.progress = progress
        cache.set(f'import_{self.task_id}', {
            'status': 'processando',
            'progress': progress,
            'message': message,
            'stats': self.stats
        }, timeout=3600)

    def flush(self):
        pass

    def getvalue(self):
        return self.buffer.getvalue()

    def get_stats(self):
        return self.stats


@shared_task(bind=True, max_retries=0)
def import_customers_task(self, task_id, start_date, end_date, import_type, empresa_slug):
    """
    Task Celery para importar clientes do WooCommerce.
    Roda em background sem bloquear o gunicorn.
    """
    logger.info(f'[CELERY] Iniciando task {task_id} para empresa {empresa_slug}')

    try:
        # Atualizar status inicial
        cache.set(f'import_{task_id}', {
            'status': 'conectando',
            'progress': 5,
            'message': 'Conectando ao servidor...',
            'celery_task_id': self.request.id
        }, timeout=3600)

        # Buffer com atualização de progresso
        out = ProgressWriter(task_id)

        # Chamar comando de importação
        call_command(
            'import_customers',
            start_date=start_date,
            end_date=end_date,
            import_type=import_type,
            empresa=empresa_slug,
            stdout=out
        )

        output = out.getvalue()
        stats = out.get_stats()

        # Construir mensagem de resumo
        resumo_parts = []
        if stats['carrinhos_sucesso'] > 0:
            resumo_parts.append(f"{stats['carrinhos_sucesso']} carrinhos")
        if stats['pedidos_total'] > 0:
            resumo_parts.append(f"{stats['pedidos_total']} pedidos")
        if stats['clientes_atualizados'] > 0:
            resumo_parts.append(f"{stats['clientes_atualizados']} clientes atualizados")
        if stats['recuperados'] > 0:
            resumo_parts.append(f"{stats['recuperados']} recuperados")

        if resumo_parts:
            resumo = f"Importados: {', '.join(resumo_parts)}"
        else:
            resumo = "Importação concluída (sem novos dados no período)"

        # Marcar como concluído
        cache.set(f'import_{task_id}', {
            'status': 'concluido',
            'progress': 100,
            'message': resumo,
            'stats': stats,
            'output': output,
            'celery_task_id': self.request.id
        }, timeout=3600)

        logger.info(f'[CELERY] Task {task_id} concluída com sucesso')
        return {'status': 'success', 'task_id': task_id}

    except Exception as e:
        error_traceback = traceback.format_exc()
        logger.error(f'[CELERY] Erro na task {task_id}: {str(e)}\n{error_traceback}')

        # Em caso de erro
        cache.set(f'import_{task_id}', {
            'status': 'erro',
            'progress': 0,
            'message': f'Erro: {str(e)}',
            'error': str(e),
            'traceback': error_traceback,
            'celery_task_id': self.request.id
        }, timeout=3600)

        return {'status': 'error', 'error': str(e)}


class LeadsProgressWriter:
    """Wrapper que captura output e atualiza progresso para importação de leads"""
    def __init__(self, task_id):
        self.task_id = task_id
        self.buffer = StringIO()
        self.progress = 10
        # Contadores para resumo final
        self.stats = {
            'novos_leads': 0,
            'ja_clientes': 0,
            'atualizados': 0,
            'total_encontrados': 0,
            'taxa_clientes': 0.0,
        }

    def write(self, msg):
        self.buffer.write(msg)

        import re

        # Capturar total de leads encontrados
        match = re.search(r'Encontrados (\d+) leads', msg)
        if match:
            self.stats['total_encontrados'] = int(match.group(1))
            self._update(30, f'Encontrados {self.stats["total_encontrados"]} leads...')
            return

        # Capturar novos leads
        match = re.search(r'Novos leads: (\d+)', msg)
        if match:
            self.stats['novos_leads'] = int(match.group(1))

        # Capturar já são clientes
        match = re.search(r'J[áa] s[ãa]o clientes: (\d+)', msg)
        if match:
            self.stats['ja_clientes'] = int(match.group(1))

        # Capturar atualizados
        match = re.search(r'Atualizados: (\d+)', msg)
        if match:
            self.stats['atualizados'] = int(match.group(1))

        # Capturar taxa de clientes
        match = re.search(r'Taxa de clientes: ([\d.]+)%', msg)
        if match:
            self.stats['taxa_clientes'] = float(match.group(1))

        # Atualizar progresso baseado nas mensagens
        if 'Conectando' in msg or 'Conexão' in msg or 'conectado' in msg.lower():
            self._update(15, 'Conectando ao banco de dados...')
        elif 'Prefixo detectado' in msg:
            self._update(25, 'Estrutura do banco detectada...')
        elif 'Buscando' in msg and 'leads' in msg:
            self._update(35, 'Buscando leads no período...')
        elif 'JÁ É CLIENTE' in msg:
            # Incrementar progresso gradualmente
            if self.progress < 85:
                self.progress += 1
                self._update(self.progress, 'Processando leads...')
        elif 'Novo lead' in msg or 'Atualizado' in msg:
            if self.progress < 85:
                self.progress += 1
                self._update(self.progress, 'Importando dados...')
        elif 'RESUMO' in msg:
            self._update(95, 'Finalizando...')

    def _update(self, progress, message):
        self.progress = progress
        cache.set(f'import_leads_{self.task_id}', {
            'status': 'processando',
            'progress': progress,
            'message': message,
            'stats': self.stats
        }, timeout=3600)

    def flush(self):
        pass

    def getvalue(self):
        return self.buffer.getvalue()

    def get_stats(self):
        return self.stats


@shared_task(bind=True, max_retries=0)
def import_leads_task(self, task_id, start_date, end_date, empresa_slug):
    """
    Task Celery para importar leads do Form Vibes.
    """
    logger.info(f'[CELERY] Iniciando importação de leads {task_id} para empresa {empresa_slug}')

    try:
        cache.set(f'import_leads_{task_id}', {
            'status': 'processando',
            'progress': 5,
            'message': 'Iniciando importação...',
            'celery_task_id': self.request.id
        }, timeout=3600)

        # Usar LeadsProgressWriter para capturar estatísticas
        out = LeadsProgressWriter(task_id)
        call_command(
            'import_leads',
            start_date=start_date,
            end_date=end_date,
            empresa=empresa_slug,
            stdout=out
        )

        output = out.getvalue()
        stats = out.get_stats()

        # Construir mensagem de resumo
        resumo_parts = []
        if stats['novos_leads'] > 0:
            resumo_parts.append(f"{stats['novos_leads']} novos leads")
        if stats['ja_clientes'] > 0:
            resumo_parts.append(f"{stats['ja_clientes']} já são clientes")
        if stats['atualizados'] > 0:
            resumo_parts.append(f"{stats['atualizados']} atualizados")

        if resumo_parts:
            resumo = f"Importados: {', '.join(resumo_parts)}"
        else:
            resumo = "Importação concluída (sem novos dados no período)"

        cache.set(f'import_leads_{task_id}', {
            'status': 'concluido',
            'progress': 100,
            'message': resumo,
            'stats': stats,
            'output': output,
            'celery_task_id': self.request.id
        }, timeout=3600)

        logger.info(f'[CELERY] Leads task {task_id} concluída com sucesso')
        return {'status': 'success', 'task_id': task_id}

    except Exception as e:
        error_traceback = traceback.format_exc()
        logger.error(f'[CELERY] Erro na leads task {task_id}: {str(e)}\n{error_traceback}')

        cache.set(f'import_leads_{task_id}', {
            'status': 'erro',
            'progress': 0,
            'message': f'Erro: {str(e)}',
            'error': str(e),
            'traceback': error_traceback,
            'celery_task_id': self.request.id
        }, timeout=3600)

        return {'status': 'error', 'error': str(e)}


@shared_task(bind=True, max_retries=0)
def check_recovery_task(self, empresa_slug):
    """
    Task Celery para verificar recuperações de carrinho.
    """
    from customers.models import Cart, Order
    from tenants.models import Empresa
    from datetime import timedelta
    from django.utils import timezone

    logger.info(f'[CELERY] Verificando recuperações para empresa {empresa_slug}')

    try:
        empresa = Empresa.objects.get(slug=empresa_slug)
        carts_qs = Cart.objects.filter(empresa=empresa)

        abandoned_carts = carts_qs.filter(
            status='abandoned',
            was_recovered=False
        )

        recovered = 0
        abandoned = 0
        waiting = 0

        for cart in abandoned_carts:
            window_end = cart.created_at + timedelta(days=30)

            recovery_order = Order.objects.filter(
                customer=cart.customer,
                created_at__gt=cart.created_at,
                created_at__lte=window_end,
                status__in=['wc-completed', 'wc-processing', 'wc-on-hold']
            ).first()

            if recovery_order:
                cart.status = 'recovered'
                cart.was_recovered = True
                cart.recovered_order = recovery_order
                cart.recovered_at = recovery_order.created_at
                cart.recovery_value = recovery_order.total
                cart.save()
                recovered += 1
            elif timezone.now() > window_end:
                abandoned += 1
            else:
                waiting += 1

        total = recovered + abandoned
        rate = (recovered / total * 100) if total > 0 else 0

        logger.info(f'[CELERY] Recuperações: {recovered}, Abandonados: {abandoned}, Aguardando: {waiting}')

        return {
            'success': True,
            'recovered': recovered,
            'abandoned': abandoned,
            'waiting': waiting,
            'rate': round(rate, 1)
        }

    except Exception as e:
        logger.error(f'[CELERY] Erro ao verificar recuperações: {str(e)}')
        return {'success': False, 'error': str(e)}
