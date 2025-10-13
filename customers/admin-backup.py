from django.contrib import admin
from django.db.models import Count, Sum, Avg
from django.utils.html import format_html
from import_export import resources
from import_export.admin import ExportMixin
from .models import Customer, Cart, Order, CustomerAnalysis

class CustomerResource(resources.ModelResource):
    class Meta:
        model = Customer
        fields = ('email', 'first_name', 'last_name', 'phone', 'whatsapp_number', 
                 'status', 'score', 'total_spent', 'completed_orders', 'abandoned_carts')

@admin.register(Customer)
class CustomerAdmin(ExportMixin, admin.ModelAdmin):
    resource_class = CustomerResource
    
    list_display = ['email', 'full_name', 'phone_display', 'status_badge', 
                   'score_display', 'total_spent_display', 'last_activity']
    
    list_filter = ['status', 'created_at', 'last_activity']
    
    search_fields = ['email', 'first_name', 'last_name', 'phone']
    
    readonly_fields = ['score', 'status', 'created_at', 'updated_at', 
                      'last_analyzed', 'whatsapp_number']
    
    fieldsets = (
        ('Identificação', {
            'fields': ('email', 'first_name', 'last_name', 'phone', 'whatsapp_number')
        }),
        ('Status e Análise', {
            'fields': ('status', 'score', 'tags', 'notes')
        }),
        ('Estatísticas', {
            'fields': ('total_orders', 'completed_orders', 'total_spent', 
                      'average_order_value', 'abandoned_carts', 'total_abandoned_value')
        }),
        ('Datas', {
            'fields': ('first_seen', 'last_purchase', 'last_activity', 
                      'created_at', 'updated_at', 'last_analyzed')
        }),
    )
    
    def phone_display(self, obj):
        if obj.whatsapp_number:
            return format_html(
                '<a href="https://wa.me/{}" target="_blank">{}</a>',
                obj.whatsapp_number, obj.phone
            )
        return obj.phone
    phone_display.short_description = 'Telefone'
    
    def status_badge(self, obj):
        colors = {
            'never_bought': 'gray',
            'first_time': 'blue',
            'returning': 'green',
            'abandoned_only': 'orange',
            'inactive': 'red',
            'vip': 'gold',
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    
    def score_display(self, obj):
        return format_html(
            '<div style="width:100px; background:#ddd;">'
            '<div style="width:{}%; background:#4CAF50; text-align:center; color:white;">{}</div>'
            '</div>',
            obj.score, obj.score
        )
    score_display.short_description = 'Score'
    
    def total_spent_display(self, obj):
        return f'R$ {obj.total_spent:,.2f}'
    total_spent_display.short_description = 'Total Gasto'
    
    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('carts', 'orders')
    
    actions = ['export_whatsapp_list', 'mark_as_contacted']
    
    def export_whatsapp_list(self, request, queryset):
        """Exporta lista para WhatsApp"""
        customers = queryset.filter(phone__isnull=False).exclude(phone='')
        
        import csv
        from django.http import HttpResponse
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="whatsapp_list.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Nome', 'WhatsApp', 'Email', 'Status', 'Score'])
        
        for customer in customers:
            if customer.whatsapp_number:
                writer.writerow([
                    customer.full_name,
                    customer.whatsapp_number,
                    customer.email,
                    customer.get_status_display(),
                    customer.score
                ])
        
        return response
    
    export_whatsapp_list.short_description = "Exportar lista WhatsApp"


@admin.register(CustomerAnalysis)
class CustomerAnalysisAdmin(admin.ModelAdmin):
    list_display = ['date', 'total_customers', 'new_customers', 
                   'abandoned_carts', 'total_revenue_display']
    
    list_filter = ['date']
    
    def total_revenue_display(self, obj):
        return f'R$ {obj.total_revenue:,.2f}'
    total_revenue_display.short_description = 'Receita Total'