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
import uuid
from django.views.decorators.csrf import csrf_exempt
from customers.models import Customer, Cart, Order


@method_decorator(staff_member_required, name='dispatch')
class ImportDashboardView(View):
    """
    View principal do dashboard de importação.
    Usa Celery para processar importações em background.
    """

    def get(self, request):
        """Renderiza o dashboard com datas padrão"""
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=30)

        context = {
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d'),
            'page_title': 'Importação e Análise Inteligente',
        }

        return render(request, 'importer/dashboard.html', context)

    def post(self, request):
        """Inicia importação via Celery task"""
        from importer.tasks import import_customers_task

        data = json.loads(request.body)
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        import_type = data.get('import_type', 'all')

        # Obter empresa do tenant logado
        empresa = getattr(request, 'tenant', None)
        empresa_slug = empresa.slug if empresa else None

        if not empresa_slug:
            return JsonResponse({
                'success': False,
                'error': 'Empresa não encontrada. Faça login novamente.'
            }, status=400)

        # Gerar ID único para esta importação
        task_id = str(uuid.uuid4())

        # Inicializar status no cache
        cache.set(f'import_{task_id}', {
            'status': 'iniciando',
            'progress': 0,
            'message': 'Preparando importação...',
            'empresa': empresa_slug,
        }, timeout=3600)

        # Executar via Celery (em background, não bloqueia)
        import_customers_task.delay(task_id, start_date, end_date, import_type, empresa_slug)

        return JsonResponse({
            'success': True,
            'task_id': task_id,
            'message': 'Importação iniciada!'
        })


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
        
        # Retornar estatísticas gerais - FILTRADO POR EMPRESA
        from customers.models import Customer, Cart, Order
        from django.db.models import Count, Sum, Q

        # Filtrar por empresa do usuário (tenant)
        empresa = getattr(request, 'tenant', None)

        # Base querysets filtrados por empresa
        if empresa:
            customers_qs = Customer.objects.filter(empresa=empresa)
            carts_qs = Cart.objects.filter(empresa=empresa)
            orders_qs = Order.objects.filter(empresa=empresa)
        elif request.user.is_superuser:
            # Superuser sem empresa selecionada vê tudo
            customers_qs = Customer.objects.all()
            carts_qs = Cart.objects.all()
            orders_qs = Order.objects.all()
        else:
            # Sem empresa, retorna vazio
            customers_qs = Customer.objects.none()
            carts_qs = Cart.objects.none()
            orders_qs = Order.objects.none()

        stats = {
            'total_customers': customers_qs.count(),
            'customers_with_phone': customers_qs.exclude(
                Q(phone='') | Q(phone__isnull=True)
            ).count(),
            'abandoned_carts': carts_qs.filter(status='abandoned').count(),
            'total_orders': orders_qs.count(),
            'recent_imports': []
        }

        # Últimas importações (últimas 24h)
        last_24h = timezone.now() - timedelta(hours=24)

        recent_customers = customers_qs.filter(
            created_at__gte=last_24h
        ).count()

        recent_carts = carts_qs.filter(
            created_at__gte=last_24h
        ).count()

        stats['recent_imports'] = {
            'customers': recent_customers,
            'carts': recent_carts,
            'last_import': customers_qs.latest('created_at').created_at.isoformat() if customers_qs.exists() else None
        }
        
        return JsonResponse(stats)

# Adicionar no final do arquivo importer/views.py

@staff_member_required
def leads_dashboard_view(request):
    """Dashboard de importação de leads do Form Vibes"""
    return render(request, 'importer/leads_dashboard.html', {
        'page_title': 'Dashboard de Leads - Form Vibes'
    })

@staff_member_required
def leads_stats_view(request):
    """Retorna estatísticas dos leads em JSON - FILTRADO POR EMPRESA"""
    from customers.models import Lead
    from django.db.models import Count

    # Filtrar por empresa do usuário (tenant)
    empresa = getattr(request, 'tenant', None)

    if empresa:
        leads_qs = Lead.objects.filter(empresa=empresa)
    elif request.user.is_superuser:
        leads_qs = Lead.objects.all()
    else:
        leads_qs = Lead.objects.none()

    total_leads = leads_qs.count()
    new_leads = leads_qs.filter(status='new').count()
    existing_customers = leads_qs.filter(is_customer=True).count()
    prospects = leads_qs.filter(is_customer=False).count()

    # Leads por status
    status_breakdown = leads_qs.values('status').annotate(count=Count('id'))

    # Leads recentes (últimas 24h)
    from datetime import timedelta
    last_24h = timezone.now() - timedelta(hours=24)
    recent_leads = leads_qs.filter(created_at__gte=last_24h).count()

    return JsonResponse({
        'total_leads': total_leads,
        'new_leads': new_leads,
        'existing_customers': existing_customers,
        'prospects': prospects,
        'recent_leads': recent_leads,
        'status_breakdown': list(status_breakdown)
    })

@csrf_exempt
@staff_member_required
def import_leads_view(request):
    """Inicia importação de leads do Form Vibes via Celery"""
    from importer.tasks import import_leads_task

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método não permitido'}, status=405)

    data = json.loads(request.body)
    start_date = data.get('start_date')
    end_date = data.get('end_date')

    # Obter empresa do tenant logado
    empresa = getattr(request, 'tenant', None)
    empresa_slug = empresa.slug if empresa else None

    if not empresa_slug:
        return JsonResponse({
            'success': False,
            'error': 'Empresa não encontrada. Faça login novamente.'
        }, status=400)

    # Gerar ID único para esta importação
    task_id = str(uuid.uuid4())

    # Inicializar status no cache
    cache.set(f'import_leads_{task_id}', {
        'status': 'iniciando',
        'progress': 0,
        'message': 'Preparando importação de leads...',
        'empresa': empresa_slug,
    }, timeout=3600)

    # Executar via Celery
    import_leads_task.delay(task_id, start_date, end_date, empresa_slug)

    return JsonResponse({
        'success': True,
        'task_id': task_id,
        'message': 'Importação de leads iniciada!'
    })

@staff_member_required
def leads_import_status_view(request):
    """Retorna status da importação de leads"""
    task_id = request.GET.get('task_id')

    if not task_id:
        return JsonResponse({'success': False, 'error': 'task_id não fornecido'}, status=400)

    status = cache.get(f'import_leads_{task_id}')

    if status:
        return JsonResponse(status)
    else:
        return JsonResponse({
            'status': 'not_found',
            'message': 'Tarefa não encontrada'
        }, status=404)

@csrf_exempt
@staff_member_required
def check_recovery_view(request):
    """Verifica recuperações de carrinho via Celery"""
    from importer.tasks import check_recovery_task

    if request.method == 'POST':
        empresa = getattr(request, 'tenant', None)
        empresa_slug = empresa.slug if empresa else None

        if not empresa_slug:
            return JsonResponse({
                'success': False,
                'error': 'Empresa não encontrada. Faça login novamente.'
            }, status=400)

        # Executar via Celery e aguardar resultado (timeout de 60s)
        result = check_recovery_task.apply_async(args=[empresa_slug])

        try:
            # Aguardar resultado com timeout
            task_result = result.get(timeout=60)
            return JsonResponse(task_result)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Erro ao verificar recuperações: {str(e)}'
            }, status=500)

    return JsonResponse({'success': False}, status=400)