from django.shortcuts import render, redirect
from django.views import View
from django.contrib import messages
from django.utils import timezone
from datetime import datetime, timedelta
from django.http import JsonResponse
from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator
import json

@method_decorator(staff_member_required, name='dispatch')
class ImportDashboardView(View):
    """View principal do dashboard de importação"""
    print('oi')

    def get(self, request):
        
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
        """Executa a importação com os parâmetros selecionados"""
        data = json.loads(request.body)
        
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        import_type = data.get('import_type', 'all')
        
        from django.core.management import call_command
        from io import StringIO
        
        out = StringIO()
        try:
            call_command(
                'import_customers',
                start_date=start_date,
                end_date=end_date,
                import_type=import_type,
                stdout=out
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Importação iniciada com sucesso!',
                'output': out.getvalue()
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erro na importação: {str(e)}'
            }, status=500)

@method_decorator(staff_member_required, name='dispatch')
class ImportStatusView(View):
    """View para verificar status da importação"""
    
    def get(self, request):
        from customers.models import Customer, Cart, Order
        from django.db.models import Count, Sum, Q
        from datetime import datetime, timedelta
        
        # Estatísticas gerais
        stats = {
            'total_customers': Customer.objects.count(),
            'customers_with_phone': Customer.objects.exclude(
                Q(phone='') | Q(phone__isnull=True)
            ).count(),
            'abandoned_carts': Cart.objects.filter(status='abandoned').count(),
            'total_orders': Order.objects.count(),
            'recent_imports': [],
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
            'last_import': Customer.objects.latest('created_at').created_at if Customer.objects.exists() else None
        }
        
        return JsonResponse(stats)