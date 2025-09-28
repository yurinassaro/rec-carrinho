from rest_framework import viewsets, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q, Count, Sum
from django_filters.rest_framework import DjangoFilterBackend
from .models import Customer
from customers.serializers import CustomerSerializer
import csv
from django.http import HttpResponse

class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'score']
    search_fields = ['email', 'first_name', 'last_name', 'phone']
    ordering_fields = ['score', 'total_spent', 'last_activity']
    ordering = ['-score']
    
    @action(detail=False, methods=['get'])
    def export_whatsapp(self, request):
        """Exporta lista para WhatsApp"""
        
        # Filtrar clientes com telefone
        customers = self.get_queryset().filter(
            Q(phone__isnull=False) & ~Q(phone='')
        )
        
        # Aplicar filtros da query
        status = request.query_params.get('status')
        if status:
            customers = customers.filter(status=status)
        
        min_score = request.query_params.get('min_score')
        if min_score:
            customers = customers.filter(score__gte=int(min_score))
        
        # Criar CSV
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="whatsapp_export.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Nome', 'WhatsApp', 'Email', 'Status', 'Score', 'Última Compra'])
        
        for customer in customers:
            if customer.whatsapp_number:
                writer.writerow([
                    customer.full_name,
                    customer.whatsapp_number,
                    customer.email,
                    customer.get_status_display(),
                    customer.score,
                    customer.last_purchase.strftime('%d/%m/%Y') if customer.last_purchase else 'Nunca'
                ])
        
        return response
    
    @action(detail=False, methods=['get'])
    def dashboard_stats(self, request):
        """Estatísticas para dashboard"""
        
        stats = {
            'total_customers': self.get_queryset().count(),
            'by_status': {},
            'potential_recovery': 0,
            'total_abandoned_value': 0,
        }
        
        # Por status
        for status, label in Customer.CUSTOMER_STATUS:
            count = self.get_queryset().filter(status=status).count()
            stats['by_status'][status] = {
                'label': label,
                'count': count,
                'percentage': (count / stats['total_customers'] * 100) if stats['total_customers'] > 0 else 0
            }
        
        # Potencial de recuperação
        abandoned_only = self.get_queryset().filter(status='abandoned_only')
        stats['potential_recovery'] = abandoned_only.count()
        stats['total_abandoned_value'] = abandoned_only.aggregate(
            Sum('total_abandoned_value')
        )['total_abandoned_value__sum'] or 0
        
        return Response(stats)