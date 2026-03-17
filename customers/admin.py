from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html
from django.urls import path
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from import_export import resources
from import_export.admin import ExportMixin
from django.db.models import Count
from .models import Customer, Cart, Order, CustomerAnalysis, Lead, MensagemWhatsApp, LeadAtacado, Pipeline, PipelineEtapa, ContatoPipeline
from tenants.admin import TenantAdminMixin
import json
from datetime import datetime
import csv


class CustomerResource(resources.ModelResource):
    class Meta:
        model = Customer
        fields = ('email', 'first_name', 'last_name', 'phone', 'whatsapp_number',
                 'status', 'score', 'total_spent', 'completed_orders', 'abandoned_carts')


class OrderInline(admin.TabularInline):
    """Pedidos do cliente exibidos inline."""
    model = Order
    extra = 0
    fields = ['order_number', 'total', 'status', 'payment_method', 'created_at', 'completed_at']
    readonly_fields = ['order_number', 'total', 'status', 'payment_method', 'created_at', 'completed_at']
    ordering = ['-created_at']
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class CartInline(admin.TabularInline):
    """Carrinhos do cliente exibidos inline."""
    model = Cart
    extra = 0
    fields = ['checkout_id', 'cart_total', 'status', 'was_recovered', 'created_at', 'recovered_at']
    readonly_fields = ['checkout_id', 'cart_total', 'status', 'was_recovered', 'created_at', 'recovered_at']
    ordering = ['-created_at']
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Customer)
class CustomerAdmin(TenantAdminMixin, ExportMixin, admin.ModelAdmin):
    resource_class = CustomerResource

    list_display = ['email', 'full_name', 'phone_display', 'status_badge',
                   'score_display', 'total_spent_display', 'orders_display',
                   'days_display', 'last_purchase', 'last_activity']

    list_filter = ['status', 'created_at', 'last_purchase', 'last_activity']
    ordering = ['-last_purchase', '-score']

    search_fields = ['email', 'first_name', 'last_name', 'phone']

    readonly_fields = ['score', 'status', 'created_at', 'updated_at',
                      'last_analyzed', 'whatsapp_number', 'days_since_last_purchase',
                      'first_purchase', 'last_purchase', 'total_orders',
                      'completed_orders', 'total_spent', 'average_order_value',
                      'abandoned_carts', 'recovered_carts', 'total_abandoned_value']

    inlines = [OrderInline, CartInline]

    fieldsets = (
        ('Identificação', {
            'fields': ('email', 'first_name', 'last_name', 'phone', 'whatsapp_number')
        }),
        ('Endereço', {
            'fields': ('billing_address', 'billing_city', 'billing_state', 'billing_postcode'),
            'classes': ('collapse',),
        }),
        ('Status e Análise', {
            'fields': ('status', 'score', 'tags', 'notes')
        }),
        ('Estatísticas de Compra', {
            'fields': ('total_orders', 'completed_orders', 'total_spent',
                      'average_order_value', 'days_since_last_purchase')
        }),
        ('Estatísticas de Carrinho', {
            'fields': ('abandoned_carts', 'recovered_carts', 'total_abandoned_value'),
            'classes': ('collapse',),
        }),
        ('Datas', {
            'fields': ('first_seen', 'first_purchase', 'last_purchase', 'last_activity',
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

    def orders_display(self, obj):
        if obj.completed_orders > 0:
            return format_html(
                '<span title="{} total / {} completos">{}/{}</span>',
                obj.total_orders, obj.completed_orders,
                obj.completed_orders, obj.total_orders,
            )
        return obj.total_orders
    orders_display.short_description = 'Pedidos'
    orders_display.admin_order_field = 'completed_orders'

    def days_display(self, obj):
        if obj.days_since_last_purchase is None:
            return '-'
        days = obj.days_since_last_purchase
        if days == 0:
            color = '#4CAF50'
            text = 'Hoje'
        elif days <= 7:
            color = '#4CAF50'
            text = f'{days}d'
        elif days <= 30:
            color = '#2196F3'
            text = f'{days}d'
        elif days <= 90:
            color = '#FF9800'
            text = f'{days}d'
        else:
            color = '#f44336'
            text = f'{days}d'
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, text,
        )
    days_display.short_description = 'Dias s/ compra'
    days_display.admin_order_field = 'days_since_last_purchase'

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
class CartAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ['get_customer_email', 'get_customer_phone', 'cart_total',
                   'status_dropdown', 'email_toggle', 'whatsapp_toggle', 'created_at']
    list_filter = ['status', 'recovery_email_sent', 'recovery_whatsapp_sent',
                  'was_recovered', 'created_at']
    search_fields = ['customer__email', 'customer__phone', 'checkout_id']

    def get_customer_email(self, obj):
        return obj.customer.email
    get_customer_email.short_description = 'Email'

    def get_customer_phone(self, obj):
        return obj.customer.whatsapp_number or obj.customer.phone or '-'
    get_customer_phone.short_description = 'Telefone'

    def status_dropdown(self, obj):
        """Dropdown para alterar status do carrinho via AJAX"""
        from django.utils.safestring import mark_safe

        colors = {
            'active': '#2196F3',
            'abandoned': '#ff9800',
            'recovered': '#4CAF50',
            'converted': '#9C27B0',
        }

        options_html = []
        for value, label in Cart.CART_STATUS:
            selected = 'selected' if value == obj.status else ''
            options_html.append(f'<option value="{value}" {selected}>{label}</option>')

        select_html = f'''
            <select class="cart-status-select"
                    data-cart-id="{obj.id}"
                    style="
                        background: {colors.get(obj.status, '#666')};
                        color: white;
                        border: none;
                        padding: 5px 10px;
                        border-radius: 4px;
                        font-weight: bold;
                        cursor: pointer;
                        font-size: 12px;
                    ">
                {''.join(options_html)}
            </select>
        '''
        return mark_safe(select_html)

    status_dropdown.short_description = 'Status'
    
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
        """Botão de status + 3 opções de envio: Web, App, WAPI"""
        import urllib.parse

        if not obj.customer.whatsapp_number:
            return format_html('<span style="color: #999;">Sem WhatsApp</span>')

        # Status atual
        if obj.recovery_whatsapp_sent:
            btn_color = '#25D366'
            btn_text = '✅ Enviado'
            if obj.recovery_whatsapp_date:
                date_text = f'<br><small style="opacity: 0.8;">{obj.recovery_whatsapp_date.strftime("%d/%m %H:%M")}</small>'
            else:
                date_text = ''
        else:
            btn_color = '#999'
            btn_text = '❌ Não Enviado'
            date_text = ''

        # Mensagem personalizada
        primeiro_nome = obj.customer.first_name.split()[0] if obj.customer.first_name else "tudo"
        msg_template = 'Olá {nome}, tudo bem ??'
        if obj.empresa and obj.empresa.msg_whatsapp_cart:
            msg_template = obj.empresa.msg_whatsapp_cart
        mensagem = msg_template.replace('{nome}', primeiro_nome)
        msg_encoded = urllib.parse.quote(mensagem)

        phone = obj.customer.whatsapp_number
        web_url = f"https://wa.me/{phone}?text={msg_encoded}"
        app_url = f"whatsapp://send?phone={phone}&text={msg_encoded}"

        # WAPI configurado? (default da empresa OU instância vinculada)
        wapi_configurado = False
        if obj.empresa:
            wapi_configurado = (
                (obj.empresa.wapi_token and obj.empresa.wapi_instance)
                or obj.empresa.instancias_wapi.filter(ativo=True).exists()
            )
        wapi_btn = ''
        if wapi_configurado:
            wapi_btn = (
                f'<button onclick="sendCartWhatsApp({obj.id}, event)"'
                f' style="background: #075E54; color: white; border: none;'
                f' padding: 4px 8px; border-radius: 3px; cursor: pointer;'
                f' font-size: 11px;" title="Enviar via W-API (automático)">'
                f'📡 WAPI</button>'
            )
        else:
            wapi_btn = (
                '<span style="color: #ccc; font-size: 10px; padding: 4px;"'
                ' title="Configure WAPI em Empresas">'
                '📡 WAPI</span>'
            )

        return format_html(
            '''
            <div style="display: flex; flex-direction: column; gap: 4px; min-width: 150px;">
                <button onclick="toggleRecovery({}, 'whatsapp', {})"
                        style="background: {}; color: white; border: none;
                            padding: 6px 10px; border-radius: 4px; cursor: pointer;
                            font-size: 11px; text-align: center;">
                    <div>{}</div>
                    {}
                </button>
                <div style="display: flex; gap: 3px; justify-content: center;">
                    <a href="{}" target="_blank" onclick="markCartWhatsApp({})"
                       style="background: #25D366; color: white; border: none;
                              padding: 4px 8px; border-radius: 3px; cursor: pointer;
                              font-size: 11px; text-decoration: none;" title="Abrir WhatsApp Web no navegador">
                        🌐 Web
                    </a>
                    <a href="{}" onclick="markCartWhatsApp({})"
                       style="background: #128C7E; color: white; border: none;
                              padding: 4px 8px; border-radius: 3px; cursor: pointer;
                              font-size: 11px; text-decoration: none;" title="Abrir WhatsApp Desktop">
                        💻 App
                    </a>
                    {}
                </div>
            </div>
            ''',
            obj.id,
            'false' if obj.recovery_whatsapp_sent else 'true',
            btn_color,
            btn_text,
            format_html(date_text) if date_text else '',
            web_url, obj.id,
            app_url, obj.id,
            format_html(wapi_btn)
        )
    whatsapp_toggle.short_description = '📱 WhatsApp'
    whatsapp_toggle.allow_tags = True

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('toggle-recovery/',
                 self.admin_site.admin_view(self.toggle_recovery),
                 name='toggle_recovery'),
            path('update-cart-status/',
                 self.admin_site.admin_view(self.update_cart_status),
                 name='update_cart_status'),
            path('send-cart-whatsapp/',
                 self.admin_site.admin_view(self.send_cart_whatsapp),
                 name='send_cart_whatsapp'),
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

    @csrf_exempt
    def send_cart_whatsapp(self, request):
        """Ajax endpoint para enviar WhatsApp via W-API"""
        if request.method == 'POST':
            try:
                data = json.loads(request.body)
                cart_id = data.get('cart_id')

                cart = get_object_or_404(Cart, id=cart_id)

                from customers.services.wapi import enviar_whatsapp_cart
                resultado = enviar_whatsapp_cart(cart, empresa=cart.empresa)

                if resultado['success']:
                    return JsonResponse({
                        'success': True,
                        'message': 'WhatsApp enviado com sucesso!',
                        'date': timezone.now().strftime('%d/%m %H:%M')
                    })
                else:
                    return JsonResponse({
                        'success': False,
                        'error': resultado.get('error', 'Erro desconhecido')
                    }, status=400)

            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)}, status=400)

        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)

    @csrf_exempt
    def update_cart_status(self, request):
        """Endpoint AJAX para atualizar status do carrinho"""
        if request.method == 'POST':
            try:
                data = json.loads(request.body)
                cart_id = data.get('cart_id')
                new_status = data.get('status')

                cart = get_object_or_404(Cart, id=cart_id)
                cart.status = new_status
                cart.save()

                # Definir cores para cada status
                colors = {
                    'active': '#2196F3',
                    'abandoned': '#ff9800',
                    'recovered': '#4CAF50',
                    'converted': '#9C27B0',
                }

                return JsonResponse({
                    'success': True,
                    'color': colors.get(new_status, '#666'),
                    'status_display': cart.get_status_display()
                })

            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)}, status=400)

        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)

    class Media:
        js = ('admin/js/cart_recovery.js',)
        css = {
            'all': ('admin/css/cart_admin.css',)
        }

# Adicionar no customers/admin.py

@admin.register(Order)
class OrderAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ['order_number', 'get_customer_name', 'get_customer_phone',
                    'total_display', 'status_badge', 'payment_method', 'created_at']
    list_filter = ['status', 'payment_method', 'created_at']
    search_fields = ['order_number', 'order_id', 'customer__email',
                     'customer__first_name', 'customer__phone']
    readonly_fields = ['order_id', 'order_number', 'customer', 'total', 'status',
                       'created_at', 'completed_at', 'items_count', 'payment_method',
                       'related_cart']
    date_hierarchy = 'created_at'

    def get_customer_name(self, obj):
        return obj.customer.full_name
    get_customer_name.short_description = 'Cliente'

    def get_customer_phone(self, obj):
        return obj.customer.phone or '-'
    get_customer_phone.short_description = 'Telefone'

    def total_display(self, obj):
        return f'R$ {obj.total:,.2f}'
    total_display.short_description = 'Total'

    def status_badge(self, obj):
        colors = {
            'completed': '#4CAF50', 'wc-completed': '#4CAF50',
            'processing': '#2196F3', 'wc-processing': '#2196F3',
            'on-hold': '#FF9800', 'wc-on-hold': '#FF9800',
            'cancelled': '#f44336', 'wc-cancelled': '#f44336',
            'refunded': '#9C27B0', 'wc-refunded': '#9C27B0',
            'pending': '#999', 'wc-pending': '#999',
        }
        color = colors.get(obj.status, '#666')
        return format_html(
            '<span style="background:{}; color:white; padding:2px 8px; '
            'border-radius:3px; font-size:11px;">{}</span>',
            color, obj.status,
        )
    status_badge.short_description = 'Status'

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(Lead)
class LeadAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ['nome', 'whatsapp_display', 'numero_sapato',
                   'status_dropdown', 'is_customer_badge', 'whatsapp_action', 'created_at']

    list_filter = ['status', 'is_customer', 'numero_sapato', 'created_at']
    search_fields = ['nome', 'whatsapp']
    readonly_fields = ['is_customer', 'related_customer', 'converted_to_customer']
    actions = ['export_leads_action']
    
    def whatsapp_display(self, obj):
        return obj.whatsapp or '-'
    whatsapp_display.short_description = 'WhatsApp'
    
    def numero_sapato(self, obj):
        return obj.numero_sapato or '-'
    numero_sapato.short_description = '👟 Nº'
    
    def status_dropdown(self, obj):
        """Dropdown para alterar status diretamente na lista"""
        from django.utils.safestring import mark_safe

        # Lista de status disponíveis
        status_choices = [
            ('new', 'Novo'),
            ('contacted', 'Contactado'),
            ('customer', 'É Cliente'),
            ('potential', 'Potencial'),
            ('lost', 'Perdido'),
        ]

        # Cores para cada status
        colors = {
            'new': '#2196F3',
            'contacted': '#FF9800',
            'customer': '#4CAF50',
            'potential': '#9C27B0',
            'lost': '#f44336'
        }

        options_html = ''
        for value, label in status_choices:
            selected = 'selected' if value == obj.status else ''
            options_html += f'<option value="{value}" {selected}>{label}</option>'

        html = f'''
            <select class="lead-status-select"
                    data-lead-id="{obj.id}"
                    style="background: {colors.get(obj.status, '#666')}; color: white; border: none;
                           padding: 5px 10px; border-radius: 4px; cursor: pointer;
                           font-weight: bold; font-size: 12px;">
                {options_html}
            </select>
        '''

        return mark_safe(html)
    status_dropdown.short_description = 'Status'
    
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
        """Botão de status + 3 opções: Web, App, WAPI"""
        if not obj.whatsapp_formatted:
            return '-'

        import urllib.parse
        primeiro_nome = obj.nome.split()[0] if obj.nome else "tudo"

        msg_template = 'Olá {nome}, tudo bem ??'
        if obj.empresa and obj.empresa.msg_whatsapp_lead:
            msg_template = obj.empresa.msg_whatsapp_lead
        mensagem = msg_template.replace('{nome}', primeiro_nome)
        msg_encoded = urllib.parse.quote(mensagem)

        phone = obj.whatsapp_formatted
        web_url = f"https://wa.me/{phone}?text={msg_encoded}"
        app_url = f"whatsapp://send?phone={phone}&text={msg_encoded}"

        # Status
        if obj.whatsapp_sent:
            btn_color = '#25D366'
            btn_text = '✅ Enviado'
            date_text = ''
            if obj.whatsapp_sent_date:
                date_text = f'<br><small style="opacity: 0.8;">{obj.whatsapp_sent_date.strftime("%d/%m %H:%M")}</small>'
            new_status = 'false'
        else:
            btn_color = '#999'
            btn_text = '❌ Não Enviado'
            date_text = ''
            new_status = 'true'

        # WAPI configurado? (default da empresa OU instância vinculada)
        wapi_configurado = False
        if obj.empresa:
            wapi_configurado = (
                (obj.empresa.wapi_token and obj.empresa.wapi_instance)
                or obj.empresa.instancias_wapi.filter(ativo=True).exists()
            )
        if wapi_configurado:
            wapi_btn = (
                f'<button onclick="sendLeadWhatsApp({obj.id}, event)"'
                f' style="background: #075E54; color: white; border: none;'
                f' padding: 4px 8px; border-radius: 3px; cursor: pointer;'
                f' font-size: 11px;" title="Enviar via W-API (automático)">'
                f'📡 WAPI</button>'
            )
        else:
            wapi_btn = (
                '<span style="color: #ccc; font-size: 10px; padding: 4px;"'
                ' title="Configure WAPI em Empresas">'
                '📡 WAPI</span>'
            )

        return format_html(
            '''
            <div style="display: flex; flex-direction: column; gap: 4px; min-width: 150px;">
                <button onclick="toggleLeadWhatsApp({}, {})"
                        style="background: {}; color: white; border: none;
                            padding: 6px 10px; border-radius: 4px; cursor: pointer;
                            font-size: 11px; text-align: center;">
                    <div>{}</div>
                    {}
                </button>
                <div style="display: flex; gap: 3px; justify-content: center;">
                    <a href="{}" target="_blank"
                       onclick="setTimeout(() => toggleLeadWhatsApp({}, true), 1000)"
                       style="background: #25D366; color: white; border: none;
                              padding: 4px 8px; border-radius: 3px; cursor: pointer;
                              font-size: 11px; text-decoration: none;" title="Abrir WhatsApp Web">
                        🌐 Web
                    </a>
                    <a href="{}"
                       onclick="setTimeout(() => toggleLeadWhatsApp({}, true), 1000)"
                       style="background: #128C7E; color: white; border: none;
                              padding: 4px 8px; border-radius: 3px; cursor: pointer;
                              font-size: 11px; text-decoration: none;" title="Abrir WhatsApp Desktop">
                        💻 App
                    </a>
                    {}
                </div>
            </div>
            ''',
            obj.id, new_status,
            btn_color,
            btn_text,
            format_html(date_text) if date_text else '',
            web_url, obj.id,
            app_url, obj.id,
            format_html(wapi_btn)
        )
    whatsapp_action.short_description = 'Ação'

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('toggle-lead-whatsapp/',
                 self.admin_site.admin_view(self.toggle_lead_whatsapp),
                 name='toggle_lead_whatsapp'),
            path('send-lead-whatsapp/',
                 self.admin_site.admin_view(self.send_lead_whatsapp),
                 name='send_lead_whatsapp'),
            path('update-lead-status/',
                 self.admin_site.admin_view(self.update_lead_status),
                 name='update_lead_status'),
            path('export-leads/',
                 self.admin_site.admin_view(self.export_leads_view),
                 name='export_leads'),
            path('export-leads/download/',
                 self.admin_site.admin_view(self.export_leads_download),
                 name='export_leads_download'),
        ]
        return custom_urls + urls

    @csrf_exempt
    def send_lead_whatsapp(self, request):
        """Ajax endpoint para enviar WhatsApp de lead via W-API"""
        if request.method == 'POST':
            try:
                data = json.loads(request.body)
                lead_id = data.get('lead_id')

                lead = Lead.objects.get(id=lead_id)

                from customers.services.wapi import enviar_whatsapp_lead
                resultado = enviar_whatsapp_lead(lead, is_customer=lead.is_customer, empresa=lead.empresa)

                if resultado['success']:
                    return JsonResponse({
                        'success': True,
                        'message': 'WhatsApp enviado com sucesso!',
                        'date': timezone.now().strftime('%d/%m %H:%M')
                    })
                else:
                    return JsonResponse({
                        'success': False,
                        'error': resultado.get('error', 'Erro desconhecido')
                    }, status=400)

            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)}, status=400)

        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)

    @csrf_exempt
    def toggle_lead_whatsapp(self, request):
        """Ajax endpoint para toggle de WhatsApp em leads"""
        if request.method == 'POST':
            try:
                data = json.loads(request.body)
                lead_id = data.get('lead_id')
                new_status = data.get('status')

                lead = Lead.objects.get(id=lead_id)
                lead.whatsapp_sent = new_status

                if new_status:
                    lead.whatsapp_sent_date = timezone.now()
                    lead.contact_attempts = (lead.contact_attempts or 0) + 1

                    # Atualizar status para 'contacted' APENAS se estiver 'new'
                    if lead.status == 'new':
                        lead.status = 'contacted'
                else:
                    lead.whatsapp_sent_date = None

                lead.save()

                return JsonResponse({
                    'success': True,
                    'new_status': new_status,
                    'date': timezone.now().strftime('%d/%m %H:%M')
                })
            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)}, status=400)

        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)

    @csrf_exempt
    def update_lead_status(self, request):
        """Ajax endpoint para atualizar status do lead"""
        if request.method == 'POST':
            try:
                data = json.loads(request.body)
                lead_id = data.get('lead_id')
                new_status = data.get('status')

                lead = Lead.objects.get(id=lead_id)
                lead.status = new_status

                # Se marcar como cliente, atualizar flag
                if new_status == 'customer':
                    lead.is_customer = True

                lead.save()

                # Retornar cor do novo status
                colors = {
                    'new': '#2196F3',
                    'contacted': '#FF9800',
                    'customer': '#4CAF50',
                    'potential': '#9C27B0',
                    'lost': '#f44336'
                }

                return JsonResponse({
                    'success': True,
                    'new_status': new_status,
                    'color': colors.get(new_status, '#666')
                })
            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)}, status=400)

        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)

    def export_leads_view(self, request):
        """View para escolher formato e filtros de exportação"""
        from django.shortcuts import render
        from datetime import datetime, timedelta

        # Definir datas padrão (últimos 30 dias)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)

        context = {
            'title': 'Exportar Leads',
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d'),
            'has_selected': 'export_lead_ids' in request.session,
            'selected_count': len(request.session.get('export_lead_ids', [])),
        }

        return render(request, 'admin/leads_export.html', context)

    def export_leads_download(self, request):
        """Processar download da exportação"""
        from django.http import HttpResponse

        # Obter parâmetros
        export_format = request.GET.get('format', 'csv')
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        use_selected = request.GET.get('use_selected') == 'true'

        # Construir queryset
        if use_selected and 'export_lead_ids' in request.session:
            lead_ids = request.session.get('export_lead_ids', [])
            queryset = Lead.objects.filter(id__in=lead_ids)
        else:
            queryset = Lead.objects.all()

            # Aplicar filtros de data
            if start_date:
                queryset = queryset.filter(created_at__gte=start_date)
            if end_date:
                queryset = queryset.filter(created_at__lte=f"{end_date} 23:59:59")

        # Ordenar por data de criação
        queryset = queryset.order_by('-created_at')

        # Exportar baseado no formato
        if export_format == 'csv':
            return self._export_csv(queryset)
        elif export_format == 'txt':
            return self._export_txt(queryset)
        elif export_format == 'xlsx':
            return self._export_xlsx(queryset)
        elif export_format == 'google_sheets':
            return self._export_google_sheets(queryset)

        return HttpResponse('Formato inválido', status=400)

    def _export_csv(self, queryset):
        """Exportar para CSV"""
        from django.http import HttpResponse

        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="leads_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'

        # Adicionar BOM para Excel reconhecer UTF-8
        response.write('\ufeff')

        writer = csv.writer(response)
        writer.writerow(['Nome', 'WhatsApp', 'Número Sapato', 'Status', 'É Cliente', 'WhatsApp Enviado', 'Data Criação'])

        for lead in queryset:
            writer.writerow([
                lead.nome,
                lead.whatsapp,
                lead.numero_sapato,
                lead.get_status_display(),
                'Sim' if lead.is_customer else 'Não',
                'Sim' if lead.whatsapp_sent else 'Não',
                lead.created_at.strftime('%d/%m/%Y %H:%M') if lead.created_at else ''
            ])

        return response

    def _export_txt(self, queryset):
        """Exportar para TXT"""
        from django.http import HttpResponse

        response = HttpResponse(content_type='text/plain; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="leads_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt"'

        # Adicionar BOM para reconhecer UTF-8
        response.write('\ufeff')

        lines = []
        lines.append('=' * 80)
        lines.append(f'EXPORTAÇÃO DE LEADS - {datetime.now().strftime("%d/%m/%Y %H:%M")}')
        lines.append('=' * 80)
        lines.append('')

        for lead in queryset:
            lines.append(f'Nome: {lead.nome}')
            lines.append(f'WhatsApp: {lead.whatsapp}')
            lines.append(f'Número do Sapato: {lead.numero_sapato}')
            lines.append(f'Status: {lead.get_status_display()}')
            lines.append(f'É Cliente: {"Sim" if lead.is_customer else "Não"}')
            lines.append(f'WhatsApp Enviado: {"Sim" if lead.whatsapp_sent else "Não"}')
            lines.append(f'Data de Criação: {lead.created_at.strftime("%d/%m/%Y %H:%M") if lead.created_at else ""}')
            lines.append('-' * 80)
            lines.append('')

        response.write('\n'.join(lines))
        return response

    def _export_xlsx(self, queryset):
        """Exportar para XLSX"""
        from django.http import HttpResponse
        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment
        except ImportError:
            return HttpResponse('Biblioteca openpyxl não instalada. Execute: pip install openpyxl', status=500)

        # Criar workbook
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Leads'

        # Estilo do cabeçalho
        header_fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
        header_font = Font(bold=True, color='FFFFFF')

        # Cabeçalhos
        headers = ['Nome', 'WhatsApp', 'Número Sapato', 'Status', 'É Cliente', 'WhatsApp Enviado', 'Data Criação']
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal='center')

        # Dados
        for row_idx, lead in enumerate(queryset, 2):
            ws.cell(row=row_idx, column=1, value=lead.nome)
            ws.cell(row=row_idx, column=2, value=lead.whatsapp)
            ws.cell(row=row_idx, column=3, value=lead.numero_sapato)
            ws.cell(row=row_idx, column=4, value=lead.get_status_display())
            ws.cell(row=row_idx, column=5, value='Sim' if lead.is_customer else 'Não')
            ws.cell(row=row_idx, column=6, value='Sim' if lead.whatsapp_sent else 'Não')
            ws.cell(row=row_idx, column=7, value=lead.created_at.strftime('%d/%m/%Y %H:%M') if lead.created_at else '')

        # Ajustar largura das colunas
        ws.column_dimensions['A'].width = 30
        ws.column_dimensions['B'].width = 20
        ws.column_dimensions['C'].width = 15
        ws.column_dimensions['D'].width = 15
        ws.column_dimensions['E'].width = 12
        ws.column_dimensions['F'].width = 18
        ws.column_dimensions['G'].width = 20

        # Salvar
        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="leads_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'
        wb.save(response)

        return response

    def _export_google_sheets(self, queryset):
        """Exportar para Google Sheets - retorna CSV para importar"""
        # Por enquanto, retornar CSV que pode ser importado no Google Sheets
        # Para integração real, seria necessário configurar Google API
        # Retorna o CSV diretamente para que o usuário possa importar no Google Sheets
        return self._export_csv(queryset)

    def export_leads_action(self, request, queryset):
        """Action para exportar leads selecionados"""
        # Armazenar IDs dos leads selecionados na sessão
        request.session['export_lead_ids'] = list(queryset.values_list('id', flat=True))
        # Redirecionar para página de exportação
        from django.shortcuts import redirect
        return redirect('/admin/customers/lead/export-leads/')
    export_leads_action.short_description = "📊 Exportar leads selecionados"

    class Media:
        js = ('admin/js/lead_admin.js',)


@admin.register(MensagemWhatsApp)
class MensagemWhatsAppAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = [
        'destinatario_nome', 'destinatario_telefone', 'tipo',
        'canal_badge', 'status_badge', 'template_name', 'created_at',
    ]
    list_filter = ['tipo', 'canal', 'status', 'created_at']
    search_fields = ['destinatario_nome', 'destinatario_telefone', 'template_name']
    readonly_fields = [
        'empresa', 'tipo', 'canal', 'status',
        'destinatario_nome', 'destinatario_telefone',
        'template_name', 'template_params', 'mensagem_texto',
        'error_message', 'api_response',
        'lead', 'cart', 'customer', 'created_at',
    ]
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def canal_badge(self, obj):
        color = '#0084ff' if obj.canal == 'meta' else '#075E54'
        label = 'Meta API' if obj.canal == 'meta' else 'W-API'
        return format_html(
            '<span style="background:{}; color:white; padding:2px 8px; '
            'border-radius:3px; font-size:11px;">{}</span>',
            color, label,
        )
    canal_badge.short_description = 'Canal'

    def status_badge(self, obj):
        colors = {
            'enviado': '#4CAF50', 'falha': '#f44336',
            'entregue': '#2196F3', 'lido': '#9C27B0',
        }
        return format_html(
            '<span style="background:{}; color:white; padding:2px 8px; '
            'border-radius:3px; font-size:11px;">{}</span>',
            colors.get(obj.status, '#999'), obj.get_status_display(),
        )
    status_badge.short_description = 'Status'


@admin.register(LeadAtacado)
class LeadAtacadoAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = [
        'nome_completo', 'whatsapp', 'cidade_estado', 'status_empresa_badge',
        'nome_empresa', 'nicho_empresarial', 'plano_interesse',
        'prioridade_badge', 'status_dropdown', 'responsavel',
        'proximo_contato_display', 'whatsapp_action', 'created_at'
    ]
    list_filter = [
        'status', 'prioridade', 'status_empresa', 'plano_interesse',
        'private_label', 'estado', 'responsavel', 'origem',
        'whatsapp_enviado', 'created_at'
    ]
    search_fields = ['nome_completo', 'email', 'whatsapp', 'cpf', 'nome_empresa', 'cnpj', 'nicho_empresarial']
    list_editable = ['responsavel']
    list_per_page = 50
    date_hierarchy = 'created_at'
    readonly_fields = ['whatsapp_enviado', 'whatsapp_enviado_em', 'whatsapp_tentativas',
                       'whatsapp_status', 'whatsapp_erro', 'ip_cliente', 'created_at', 'updated_at']
    actions = ['enviar_whatsapp_wapi', 'enviar_whatsapp_meta', 'marcar_conversando',
               'marcar_potencial', 'marcar_passado_vendedor', 'export_csv']

    fieldsets = (
        ('Dados Pessoais', {
            'fields': ('nome_completo', 'cpf', 'email', 'whatsapp', 'cidade', 'estado')
        }),
        ('Perfil', {
            'fields': ('status_empresa', 'plano_interesse', 'private_label')
        }),
        ('Dados da Empresa', {
            'fields': ('nome_empresa', 'cnpj', 'nicho_empresarial', 'instagram', 'site_vendas'),
        }),
        ('Canais / Sobre', {
            'fields': ('canais_vendas', 'sobre_voce'),
            'classes': ('collapse',),
        }),
        ('CRM', {
            'fields': ('status', 'prioridade', 'responsavel', 'proximo_contato', 'valor_estimado', 'notas'),
            'description': 'Gestão do lead no pipeline de vendas',
        }),
        ('WhatsApp', {
            'fields': ('whatsapp_enviado', 'whatsapp_enviado_em', 'whatsapp_tentativas',
                       'whatsapp_status', 'whatsapp_erro'),
            'classes': ('collapse',),
        }),
        ('Metadados', {
            'fields': ('origem', 'ip_cliente', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def cidade_estado(self, obj):
        if obj.cidade and obj.estado:
            return f'{obj.cidade}/{obj.estado}'
        return obj.cidade or obj.estado or '-'
    cidade_estado.short_description = 'Local'

    def status_empresa_badge(self, obj):
        if not obj.status_empresa:
            return '-'
        colors = {
            'tenho_empresa_vendo_calcados': '#48bb78',
            'tenho_empresa_nao_vendo_sapatos': '#ecc94b',
            'nao_tenho_empresa_vendo_sapatos': '#ed8936',
            'nao_tenho_empresa_nao_vendo_sapatos': '#e53e3e',
        }
        labels = {
            'tenho_empresa_vendo_calcados': 'Emp+Calçados',
            'tenho_empresa_nao_vendo_sapatos': 'Emp+Outro',
            'nao_tenho_empresa_vendo_sapatos': 'S/Emp+Calçados',
            'nao_tenho_empresa_nao_vendo_sapatos': 'S/Emp+Outro',
        }
        color = colors.get(obj.status_empresa, '#999')
        label = labels.get(obj.status_empresa, '?')
        tc = '#000' if obj.status_empresa == 'tenho_empresa_nao_vendo_sapatos' else '#fff'
        return format_html(
            '<span style="background:{}; color:{}; padding:2px 6px; border-radius:4px; '
            'font-size:10px; font-weight:bold; white-space:nowrap;">{}</span>',
            color, tc, label,
        )
    status_empresa_badge.short_description = 'Tipo'

    def prioridade_badge(self, obj):
        colors = {'baixa': '#9E9E9E', 'media': '#2196F3', 'alta': '#FF9800', 'urgente': '#f44336'}
        return format_html(
            '<span style="background:{}; color:white; padding:2px 6px; border-radius:3px; '
            'font-size:10px; font-weight:bold;">{}</span>',
            colors.get(obj.prioridade, '#999'), obj.get_prioridade_display(),
        )
    prioridade_badge.short_description = 'Prior.'

    def proximo_contato_display(self, obj):
        if not obj.proximo_contato:
            return '-'
        now = timezone.now()
        if obj.proximo_contato < now:
            return format_html(
                '<span style="color:#f44336; font-weight:bold;" title="{}">{}</span>',
                obj.proximo_contato.strftime('%d/%m/%Y %H:%M'),
                'ATRASADO',
            )
        return format_html(
            '<span title="{}">{}</span>',
            obj.proximo_contato.strftime('%d/%m/%Y %H:%M'),
            obj.proximo_contato.strftime('%d/%m %H:%M'),
        )
    proximo_contato_display.short_description = 'Follow-up'

    def status_dropdown(self, obj):
        colors = {
            'novo': '#2196F3', 'conversando': '#FF9800', 'potencial': '#9C27B0',
            'nao_potencial': '#795548', 'passado_vendedor': '#00BCD4',
            'curioso': '#607D8B', 'convertido': '#4CAF50', 'perdido': '#f44336',
        }
        options = ''.join(
            f'<option value="{v}" {"selected" if v == obj.status else ""}>{l}</option>'
            for v, l in LeadAtacado.LEAD_STATUS
        )
        return format_html(
            '<select class="lead-atacado-status" data-id="{}" '
            'style="background:{}; color:white; border:none; padding:4px 8px; '
            'border-radius:4px; cursor:pointer; font-weight:bold; font-size:11px;">'
            '{}</select>',
            obj.id, colors.get(obj.status, '#666'), format_html(options),
        )
    status_dropdown.short_description = 'Status'

    def whatsapp_action(self, obj):
        icon = ''
        if obj.whatsapp_enviado:
            icon = ' <span style="color:#4CAF50;" title="Enviado">&#10004;</span>'
        if not obj.whatsapp:
            return format_html('<span style="color:#999;">sem tel</span>')
        return format_html(
            '<a href="#" class="send-wapi-atacado" data-id="{}" '
            'style="background:#25D366; color:white; padding:3px 8px; border-radius:4px; '
            'text-decoration:none; font-size:11px; font-weight:bold;">Zap</a>{}',
            obj.id, format_html(icon),
        )
    whatsapp_action.short_description = 'WhatsApp'

    def enviar_whatsapp_wapi(self, request, queryset):
        from .api_lead_atacado import enviar_whatsapp_lead_atacado
        enviados = falhas = 0
        for lead in queryset.exclude(whatsapp=''):
            r = enviar_whatsapp_lead_atacado(lead, canal='wapi')
            if r.get('success'):
                enviados += 1
            else:
                falhas += 1
        self.message_user(request, f'W-API: {enviados} enviados, {falhas} falhas.')
    enviar_whatsapp_wapi.short_description = 'Enviar WhatsApp (W-API)'

    def enviar_whatsapp_meta(self, request, queryset):
        from .api_lead_atacado import enviar_whatsapp_lead_atacado
        enviados = falhas = 0
        for lead in queryset.exclude(whatsapp=''):
            r = enviar_whatsapp_lead_atacado(lead, canal='meta')
            if r.get('success'):
                enviados += 1
            else:
                falhas += 1
        self.message_user(request, f'Meta API: {enviados} enviados, {falhas} falhas.')
    enviar_whatsapp_meta.short_description = 'Enviar WhatsApp (Meta Cloud API)'

    def marcar_conversando(self, request, queryset):
        updated = queryset.update(status='conversando')
        self.message_user(request, f'{updated} leads marcados como Conversando.')
    marcar_conversando.short_description = 'Marcar: Conversando'

    def marcar_potencial(self, request, queryset):
        updated = queryset.update(status='potencial')
        self.message_user(request, f'{updated} leads marcados como Potencial.')
    marcar_potencial.short_description = 'Marcar: Potencial'

    def marcar_passado_vendedor(self, request, queryset):
        updated = queryset.update(status='passado_vendedor')
        self.message_user(request, f'{updated} leads marcados como Passado p/ Vendedor.')
    marcar_passado_vendedor.short_description = 'Marcar: Passado p/ Vendedor'

    def export_csv(self, request, queryset):
        from django.http import HttpResponse
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="leads_atacado.csv"'
        writer = csv.writer(response)
        writer.writerow(['Nome', 'WhatsApp', 'Email', 'CPF', 'Cidade', 'Estado',
                         'Status Empresa', 'Nome Empresa', 'CNPJ', 'Nicho',
                         'Plano', 'Private Label', 'Status', 'Prioridade',
                         'Responsável', 'Próximo Contato', 'Data Cadastro'])
        for lead in queryset:
            writer.writerow([
                lead.nome_completo, lead.whatsapp, lead.email, lead.cpf,
                lead.cidade, lead.estado, lead.get_status_empresa_display(),
                lead.nome_empresa, lead.cnpj, lead.nicho_empresarial,
                lead.plano_interesse, lead.private_label, lead.get_status_display(),
                lead.get_prioridade_display(), lead.responsavel,
                lead.proximo_contato.strftime('%d/%m/%Y %H:%M') if lead.proximo_contato else '',
                lead.created_at.strftime('%d/%m/%Y %H:%M'),
            ])
        return response
    export_csv.short_description = 'Exportar CSV'

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('pipeline/',
                 self.admin_site.admin_view(self.pipeline_view),
                 name='lead_atacado_pipeline'),
            path('enviar-whatsapp/<int:lead_id>/',
                 self.admin_site.admin_view(self.enviar_whatsapp_individual),
                 name='lead_atacado_enviar_whatsapp'),
            path('alterar-status/<int:lead_id>/',
                 self.admin_site.admin_view(self.alterar_status_ajax),
                 name='lead_atacado_alterar_status'),
        ]
        return custom_urls + urls

    def pipeline_view(self, request):
        """Vista pipeline/kanban dos leads"""
        from django.template.response import TemplateResponse
        from django.db.models import Count, Sum

        # Filtro por empresa (tenant)
        qs = LeadAtacado.objects.all()
        if not request.user.is_superuser and hasattr(request.user, 'empresa') and request.user.empresa:
            qs = qs.filter(empresa=request.user.empresa)

        # Stats por status
        pipeline = {}
        for status_key, status_label in LeadAtacado.LEAD_STATUS:
            leads = qs.filter(status=status_key).order_by('-updated_at')[:50]
            pipeline[status_key] = {
                'label': status_label,
                'leads': leads,
                'count': qs.filter(status=status_key).count(),
            }

        # Stats gerais
        total = qs.count()
        stats = {
            'total': total,
            'novos': qs.filter(status='novo').count(),
            'conversando': qs.filter(status='conversando').count(),
            'potencial': qs.filter(status='potencial').count(),
            'convertidos': qs.filter(status='convertido').count(),
            'follow_up_atrasado': qs.filter(
                proximo_contato__lt=timezone.now(),
                status__in=['novo', 'conversando', 'potencial']
            ).count(),
        }

        context = {
            **self.admin_site.each_context(request),
            'title': 'Pipeline - Leads Atacado',
            'pipeline': pipeline,
            'stats': stats,
            'status_colors': {
                'novo': '#2196F3', 'conversando': '#FF9800', 'potencial': '#9C27B0',
                'nao_potencial': '#795548', 'passado_vendedor': '#00BCD4',
                'curioso': '#607D8B', 'convertido': '#4CAF50', 'perdido': '#f44336',
            },
        }
        return TemplateResponse(request, 'admin/customers/leadatacado/pipeline.html', context)

    @csrf_exempt
    def enviar_whatsapp_individual(self, request, lead_id):
        from .api_lead_atacado import enviar_whatsapp_lead_atacado
        lead = get_object_or_404(LeadAtacado, pk=lead_id)
        mensagem = request.POST.get('mensagem', '') if request.method == 'POST' else ''
        canal = request.POST.get('canal', 'wapi') if request.method == 'POST' else 'wapi'
        resultado = enviar_whatsapp_lead_atacado(
            lead,
            mensagem_texto=mensagem if mensagem else None,
            canal=canal
        )
        return JsonResponse(resultado)

    @csrf_exempt
    def alterar_status_ajax(self, request, lead_id):
        if request.method == 'POST':
            try:
                data = json.loads(request.body)
                lead = get_object_or_404(LeadAtacado, pk=lead_id)
                lead.status = data.get('status', lead.status)
                lead.save(update_fields=['status', 'updated_at'])
                return JsonResponse({'success': True})
            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)})
        return JsonResponse({'success': False, 'error': 'POST required'})

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        # Stats rápidos no topo da lista
        qs = self.get_queryset(request)
        extra_context['pipeline_stats'] = {
            'total': qs.count(),
            'novos': qs.filter(status='novo').count(),
            'conversando': qs.filter(status='conversando').count(),
            'potencial': qs.filter(status='potencial').count(),
            'convertidos': qs.filter(status='convertido').count(),
        }
        return super().changelist_view(request, extra_context=extra_context)

    class Media:
        js = ('js/lead_atacado_admin.js',)


class PipelineEtapaInline(admin.TabularInline):
    model = PipelineEtapa
    extra = 3
    fields = ['nome', 'cor', 'ordem', 'is_final']
    ordering = ['ordem']


@admin.register(Pipeline)
class PipelineAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ['nome', 'empresa', 'ativo', 'ordem']
    list_filter = ['empresa', 'ativo']
    prepopulated_fields = {'slug': ('nome',)}
    inlines = [PipelineEtapaInline]


@admin.register(ContatoPipeline)
class ContatoPipelineAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ['nome', 'telefone', 'pipeline', 'etapa', 'prioridade', 'responsavel', 'created_at']
    list_filter = ['empresa', 'pipeline', 'etapa', 'prioridade']
    search_fields = ['nome', 'telefone', 'email', 'empresa_contato']
    list_editable = ['etapa', 'prioridade', 'responsavel']
    raw_id_fields = ['customer']