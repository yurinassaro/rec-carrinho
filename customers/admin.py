from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html
from django.urls import path
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from import_export import resources
from import_export.admin import ExportMixin
from django.db.models import Count, Sum, Avg
from .models import Customer, Cart, Order, CustomerAnalysis
import json

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

@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ['get_customer_email', 'get_customer_phone', 'cart_total', 
                   'status_badge', 'email_toggle', 'whatsapp_toggle', 'created_at']
    list_filter = ['status', 'recovery_email_sent', 'recovery_whatsapp_sent', 
                  'was_recovered', 'created_at']
    search_fields = ['customer__email', 'customer__phone', 'checkout_id']
    
    def get_customer_email(self, obj):
        return obj.customer.email
    get_customer_email.short_description = 'Email'
    
    def get_customer_phone(self, obj):
        return obj.customer.whatsapp_number or obj.customer.phone or '-'
    get_customer_phone.short_description = 'Telefone'
    
    def status_badge(self, obj):
        colors = {
            'abandoned': '#ff9800',
            'recovered': '#4CAF50',
            'active': '#2196F3'
        }
        return format_html(
            '<span style="background: {}; color: white; padding: 3px 10px; '
            'border-radius: 3px; font-size: 11px;">{}</span>',
            colors.get(obj.status, '#666'),
            obj.get_status_display().upper()
        )
    status_badge.short_description = 'Status'
    
    def email_toggle(self, obj):
        """Botão toggle para marcar envio de email"""
        if obj.recovery_email_sent:
            btn_color = '#4CAF50'
            btn_text = '✅ Email Enviado'
            if obj.recovery_email_date:
                date_text = f'<br><small style="opacity: 0.8;">{obj.recovery_email_date.strftime("%d/%m %H:%M")}</small>'
            else:
                date_text = ''
        else:
            btn_color = '#f44336'
            btn_text = '❌ Não Enviado'
            date_text = ''
        
        return format_html(
            '''
            <button onclick="toggleRecovery({}, 'email', {})" 
                    style="background: {}; color: white; border: none; 
                        padding: 8px 12px; border-radius: 4px; cursor: pointer;
                        font-size: 12px; min-width: 140px; text-align: center;">
                <div>{}</div>
                {}
            </button>
            ''',
            obj.id, 
            'false' if obj.recovery_email_sent else 'true',
            btn_color,
            btn_text,
            format_html(date_text) if date_text else ''
        )
    
    email_toggle.short_description = '📧 Email'
    email_toggle.allow_tags = True  # Adicionar esta linha

    def whatsapp_toggle(self, obj):
        """Botão toggle para marcar envio de WhatsApp"""
        if not obj.customer.whatsapp_number:
            return format_html('<span style="color: #999;">Sem WhatsApp</span>')
        
        if obj.recovery_whatsapp_sent:
            btn_color = '#25D366'
            btn_text = '✅ WhatsApp Enviado'
            if obj.recovery_whatsapp_date:
                date_text = f'<br><small style="opacity: 0.8;">{obj.recovery_whatsapp_date.strftime("%d/%m %H:%M")}</small>'
            else:
                date_text = ''
        else:
            btn_color = '#999'
            btn_text = '❌ Não Enviado'
            date_text = ''
        
        # Mensagem para o cliente
        mensagem = "Olá! Vi que você deixou alguns itens no carrinho..."
        
        return format_html(
            '''
            <div style="display: flex; align-items: center; gap: 5px;">
                <button onclick="toggleRecovery({}, 'whatsapp', {})" 
                        style="background: {}; color: white; border: none; 
                            padding: 8px 12px; border-radius: 4px; cursor: pointer;
                            font-size: 12px; min-width: 140px; text-align: center;">
                    <div>{}</div>
                    {}
                </button>
                <button onclick="openWhatsApp('{}', '{}')"
                        style="background: #25D366; color: white; border: none;
                            padding: 8px; border-radius: 4px; cursor: pointer;
                            font-size: 16px;" title="Abrir WhatsApp">
                    📱
                </button>
            </div>
            ''',
            obj.id,
            'false' if obj.recovery_whatsapp_sent else 'true',
            btn_color,
            btn_text,
            format_html(date_text) if date_text else '',
            obj.customer.whatsapp_number,
            obj.id
        )
    whatsapp_toggle.short_description = '📱 WhatsApp'
    whatsapp_toggle.allow_tags = True

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('toggle-recovery/', 
                 self.admin_site.admin_view(self.toggle_recovery), 
                 name='toggle_recovery'),
        ]
        return custom_urls + urls
    
    @csrf_exempt
    def toggle_recovery(self, request):
        """Ajax endpoint para toggle de status"""
        if request.method == 'POST':
            data = json.loads(request.body)
            cart_id = data.get('cart_id')
            field_type = data.get('type')  # 'email' ou 'whatsapp'
            new_status = data.get('status')  # true ou false
            
            cart = get_object_or_404(Cart, id=cart_id)
            
            if field_type == 'email':
                cart.recovery_email_sent = new_status
                if new_status:
                    cart.recovery_email_date = timezone.now()
                    cart.recovery_attempts = (cart.recovery_attempts or 0) + 1
                else:
                    cart.recovery_email_date = None
            
            elif field_type == 'whatsapp':
                cart.recovery_whatsapp_sent = new_status
                if new_status:
                    cart.recovery_whatsapp_date = timezone.now()
                    cart.recovery_attempts = (cart.recovery_attempts or 0) + 1
                else:
                    cart.recovery_whatsapp_date = None
            
            cart.save()
            
            return JsonResponse({
                'success': True,
                'new_status': new_status,
                'date': timezone.now().strftime('%d/%m %H:%M')
            })
        
        return JsonResponse({'success': False})
    
    class Media:
        js = ('admin/js/cart_recovery.js',)
        css = {
            'all': ('admin/css/cart_admin.css',)
        }

# Adicionar no customers/admin.py

@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ['nome', 'whatsapp_display', 'numero_sapato', 
                   'status_badge', 'is_customer_badge', 'whatsapp_action', 'created_at']
    
    list_filter = ['status', 'is_customer', 'numero_sapato', 'created_at']
    search_fields = ['nome', 'whatsapp']
    readonly_fields = ['is_customer', 'related_customer', 'converted_to_customer']
    
    def whatsapp_display(self, obj):
        return obj.whatsapp or '-'
    whatsapp_display.short_description = 'WhatsApp'
    
    def numero_sapato(self, obj):
        return obj.numero_sapato or '-'
    numero_sapato.short_description = '👟 Nº'
    
    def status_badge(self, obj):
        colors = {
            'new': '#2196F3',
            'contacted': '#FF9800',
            'customer': '#4CAF50',
            'potential': '#9C27B0',
            'lost': '#f44336'
        }
        return format_html(
            '<span style="background: {}; color: white; padding: 3px 10px; '
            'border-radius: 3px; font-size: 11px;">{}</span>',
            colors.get(obj.status, '#666'),
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    
    def is_customer_badge(self, obj):
        if obj.is_customer:
            return format_html(
                '<span style="background: #4CAF50; color: white; padding: 3px 10px; '
                'border-radius: 3px;">✅ Cliente</span>'
            )
        return format_html(
            '<span style="background: #FF9800; color: white; padding: 3px 10px; '
            'border-radius: 3px;">🆕 Prospect</span>'
        )
    is_customer_badge.short_description = 'Tipo'
    
    def whatsapp_action(self, obj):
        if not obj.whatsapp_formatted:
            return '-'
        
        if obj.whatsapp_sent:
            date_info = obj.whatsapp_sent_date.strftime("%d/%m %H:%M") if obj.whatsapp_sent_date else ''
            return format_html(
                '''
                <button style="background: #25D366; color: white; padding: 5px 10px; 
                        border: none; border-radius: 4px; font-size: 11px;">
                    ✅ Enviado<br><small>{}</small>
                </button>
                ''',
                date_info
            )
        
        # Mensagem personalizada baseado no status
        if obj.is_customer:
            msg = "Olá {}! Vi que você se interessou pelo sapato nº {}. Como nosso cliente especial, temos condições exclusivas!"
        else:
            msg = "Olá {}! Vi seu interesse no sapato nº {}. Temos promoções imperdíveis! Posso ajudar?"
        
        msg = msg.format(obj.nome.split()[0], obj.numero_sapato)
        
        return format_html(
            '''
            <button onclick="markLeadContacted({})"
                    style="background: #25D366; color: white; padding: 8px 12px; 
                           border: none; border-radius: 4px; cursor: pointer;">
                📱 WhatsApp
            </button>
            ''',
            obj.id
        )
    whatsapp_action.short_description = 'Ação'
    
    class Media:
        js = ('admin/js/lead_admin.js',)