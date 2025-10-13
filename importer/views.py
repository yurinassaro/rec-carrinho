# importer/views.py

from django.shortcuts import render, redirect
from django.views import View
from django.contrib import messages
from django.utils import timezone
from datetime import datetime, timedelta
from django.http import JsonResponse
from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator
from django.core.cache import cache
import json
import threading
import uuid
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from customers.models import Customer, Cart, Order

@method_decorator(staff_member_required, name='dispatch')
class ImportDashboardView(View):
    """
    # Classe: ImportDashboardView
    # Descrição: View principal do dashboard de importação
    # Métodos:
    #   - get: Renderiza o dashboard
    #   - post: Inicia processo de importação
    """
    
    def get(self, request):
        """
        # Método: get
        # Descrição: Renderiza o dashboard com datas padrão
        # Parâmetros:
        #   - request (HttpRequest): requisição HTTP
        # Retorno:
        #   - HttpResponse: template renderizado
        """
        # Definir datas padrão (últimos 30 dias até hoje)
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=30)
        
        context = {
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d'),
            'page_title': 'Importação e Análise Inteligente',
        }
        
        return render(request, 'importer/dashboard.html', context)
    
    def post(self, request):
        """
        # Método: post
        # Descrição: Inicia importação em thread separada com progresso
        # Parâmetros:
        #   - request (HttpRequest): contém start_date, end_date, import_type
        # Retorno:
        #   - JsonResponse: task_id para acompanhamento
        """
        data = json.loads(request.body)
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        import_type = data.get('import_type', 'all')
        
        # Gerar ID único para esta importação
        task_id = str(uuid.uuid4())
        
        # Inicializar status no cache
        cache.set(f'import_{task_id}', {
            'status': 'iniciando',
            'progress': 0,
            'message': 'Preparando importação...',
            'current': 0,
            'total': 0,
            'stats': {
                'clientes_novos': 0,
                'clientes_atualizados': 0,
                'carrinhos_importados': 0,
                'pedidos_importados': 0
            }
        }, timeout=3600)  # 1 hora
        
        # Executar importação em thread
        thread = threading.Thread(
            target=self._run_import,
            args=(task_id, start_date, end_date, import_type)
        )
        thread.daemon = True
        thread.start()
        
        return JsonResponse({
            'success': True,
            'task_id': task_id,
            'message': 'Importação iniciada!'
        })
    
    def _run_import(self, task_id, start_date, end_date, import_type):
        """
        # Método: _run_import
        # Descrição: Executa importação em background com atualização de progresso
        # Parâmetros:
        #   - task_id (str): ID único da tarefa
        #   - start_date (str): data inicial YYYY-MM-DD
        #   - end_date (str): data final YYYY-MM-DD
        #   - import_type (str): tipo de importação
        # Retorno:
        #   - None: atualiza cache durante execução
        """
        from django.core.management import call_command
        from io import StringIO
        import sys
        
        # Criar um wrapper para capturar output e atualizar progresso
        class ProgressCapture:
            def __init__(self, task_id):
                self.task_id = task_id
                self.buffer = StringIO()
                
            def write(self, msg):
                self.buffer.write(msg)
                
                # Atualizar progresso baseado nas mensagens
                if '📦 Processando' in msg:
                    # Extrair números da mensagem tipo "Processando X carrinhos"
                    import re
                    numbers = re.findall(r'\d+', msg)
                    if numbers:
                        total = int(numbers[0])
                        cache_data = cache.get(f'import_{self.task_id}') or {}
                        cache_data.update({
                            'status': 'processando',
                            'progress': 20,
                            'message': msg.strip(),
                            'total': total
                        })
                        cache.set(f'import_{self.task_id}', cache_data, timeout=3600)
                
                elif '✅' in msg and 'processados' in msg:
                    # Atualizar contagem processada
                    import re
                    numbers = re.findall(r'\d+', msg)
                    if numbers:
                        current = int(numbers[0])
                        cache_data = cache.get(f'import_{self.task_id}') or {}
                        total = cache_data.get('total', 100)
                        progress = min(90, int((current / total) * 80)) if total > 0 else 50
                        cache_data.update({
                            'current': current,
                            'progress': progress,
                            'message': f'Processando item {current} de {total}'
                        })
                        cache.set(f'import_{self.task_id}', cache_data, timeout=3600)
                
                elif '🛍️ Processando' in msg and 'pedidos' in msg:
                    cache_data = cache.get(f'import_{self.task_id}') or {}
                    cache_data.update({
                        'status': 'processando',
                        'progress': 60,
                        'message': 'Importando pedidos...'
                    })
                    cache.set(f'import_{self.task_id}', cache_data, timeout=3600)
                
                elif '🧠 Executando análise' in msg:
                    cache_data = cache.get(f'import_{self.task_id}') or {}
                    cache_data.update({
                        'status': 'analisando',
                        'progress': 85,
                        'message': 'Executando análise inteligente...'
                    })
                    cache.set(f'import_{self.task_id}', cache_data, timeout=3600)
                
                elif '📊 Resumo' in msg:
                    # Extrair estatísticas finais
                    cache_data = cache.get(f'import_{self.task_id}') or {}
                    cache_data.update({
                        'status': 'finalizando',
                        'progress': 95,
                        'message': 'Finalizando importação...'
                    })
                    cache.set(f'import_{self.task_id}', cache_data, timeout=3600)
                
                elif '✅ Importação concluída' in msg:
                    cache_data = cache.get(f'import_{self.task_id}') or {}
                    cache_data.update({
                        'status': 'concluido',
                        'progress': 100,
                        'message': 'Importação concluída com sucesso!'
                    })
                    cache.set(f'import_{self.task_id}', cache_data, timeout=3600)
            
            def flush(self):
                pass
        
        out = ProgressCapture(task_id)
        
        try:
            # Atualizar status inicial
            cache_data = cache.get(f'import_{task_id}') or {}
            cache_data.update({
                'status': 'conectando',
                'progress': 5,
                'message': 'Conectando ao servidor...'
            })
            cache.set(f'import_{task_id}', cache_data, timeout=3600)
            
            # Chamar comando de importação
            call_command(
                'import_customers',
                start_date=start_date,
                end_date=end_date,
                import_type=import_type,
                stdout=out
            )
            
            # Marcar como concluído
            cache_data = cache.get(f'import_{task_id}') or {}
            cache_data.update({
                'status': 'concluido',
                'progress': 100,
                'message': 'Importação concluída com sucesso!',
                'output': out.buffer.getvalue()
            })
            cache.set(f'import_{task_id}', cache_data, timeout=3600)
            
        except Exception as e:
            # Em caso de erro
            cache_data = cache.get(f'import_{task_id}') or {}
            cache_data.update({
                'status': 'erro',
                'progress': 0,
                'message': f'Erro: {str(e)}',
                'error': str(e)
            })
            cache.set(f'import_{task_id}', cache_data, timeout=3600)


@method_decorator(staff_member_required, name='dispatch')
class ImportStatusView(View):
    """
    # Classe: ImportStatusView
    # Descrição: View para verificar status e progresso da importação
    # Métodos:
    #   - get: Retorna estatísticas ou progresso da importação
    """
    
    def get(self, request):
        """
        # Método: get
        # Descrição: Retorna status da importação ou estatísticas gerais
        # Parâmetros:
        #   - request (HttpRequest): pode conter task_id como query param
        # Retorno:
        #   - JsonResponse: status/progresso ou estatísticas
        """
        task_id = request.GET.get('task_id')
        
        if task_id:
            # Retornar status da tarefa específica
            status = cache.get(f'import_{task_id}')
            if status:
                return JsonResponse(status)
            else:
                return JsonResponse({
                    'status': 'not_found',
                    'message': 'Tarefa não encontrada'
                }, status=404)
        
        # Retornar estatísticas gerais
        from customers.models import Customer, Cart, Order
        from django.db.models import Count, Sum, Q
        
        stats = {
            'total_customers': Customer.objects.count(),
            'customers_with_phone': Customer.objects.exclude(
                Q(phone='') | Q(phone__isnull=True)
            ).count(),
            'abandoned_carts': Cart.objects.filter(status='abandoned').count(),
            'total_orders': Order.objects.count(),
            'recent_imports': []
        }
        
        # Últimas importações (últimas 24h)
        last_24h = timezone.now() - timedelta(hours=24)
        
        recent_customers = Customer.objects.filter(
            created_at__gte=last_24h
        ).count()
        
        recent_carts = Cart.objects.filter(
            created_at__gte=last_24h
        ).count()
        
        stats['recent_imports'] = {
            'customers': recent_customers,
            'carts': recent_carts,
            'last_import': Customer.objects.latest('created_at').created_at.isoformat() if Customer.objects.exists() else None
        }
        
        return JsonResponse(stats)

# Adicionar no final do arquivo importer/views.py

@csrf_exempt
@staff_member_required
def check_recovery_view(request):
    from customers.models import Cart, Order
    from datetime import timedelta
    from django.utils import timezone
    
    if request.method == 'POST':
        abandoned_carts = Cart.objects.filter(
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
        
        return JsonResponse({
            'success': True,
            'recovered': recovered,
            'abandoned': abandoned,
            'waiting': waiting,
            'rate': round(rate, 1)
        })
    
    return JsonResponse({'success': False}, status=400)