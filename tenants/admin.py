import hashlib
from django.contrib import admin, messages
from django.contrib.auth.models import User
from django.utils.html import format_html
from django.urls import path, reverse
from django.http import HttpResponseRedirect
from .models import Empresa, EmpresaUsuario, InstanciaWAPI


class TenantAdminMixin:
    """
    Mixin para ModelAdmin que filtra automaticamente por tenant
    """

    def get_queryset(self, request):
        """Filtra queryset pelo tenant atual"""
        qs = super().get_queryset(request)

        # Superuser ve tudo
        if request.user.is_superuser:
            return qs

        # Filtrar por tenant
        tenant = getattr(request, 'tenant', None)
        if tenant and hasattr(self.model, 'empresa'):
            return qs.filter(empresa=tenant)

        return qs

    def save_model(self, request, obj, form, change):
        """Adiciona tenant automaticamente ao criar"""
        if not change and hasattr(obj, 'empresa'):
            tenant = getattr(request, 'tenant', None)
            if tenant and not obj.empresa_id:
                obj.empresa = tenant

        super().save_model(request, obj, form, change)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Filtra FKs pelo tenant"""
        tenant = getattr(request, 'tenant', None)

        if tenant:
            # Filtrar Customer pelo tenant
            if db_field.name == 'customer':
                from customers.models import Customer
                kwargs['queryset'] = Customer.objects.filter(empresa=tenant)
            # Filtrar Cart pelo tenant
            elif db_field.name in ['related_cart', 'recovered_order']:
                from customers.models import Cart, Order
                if db_field.name == 'related_cart':
                    kwargs['queryset'] = Cart.objects.filter(empresa=tenant)
                elif db_field.name == 'recovered_order':
                    kwargs['queryset'] = Order.objects.filter(empresa=tenant)

        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def has_change_permission(self, request, obj=None):
        """Verifica permissao de edicao baseado no tenant"""
        if obj and hasattr(obj, 'empresa'):
            tenant = getattr(request, 'tenant', None)
            if tenant and obj.empresa != tenant and not request.user.is_superuser:
                return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        """Verifica permissao de exclusao baseado no tenant"""
        if obj and hasattr(obj, 'empresa'):
            tenant = getattr(request, 'tenant', None)
            if tenant and obj.empresa != tenant and not request.user.is_superuser:
                return False
        return super().has_delete_permission(request, obj)


class InstanciaWAPIInline(admin.TabularInline):
    model = InstanciaWAPI
    extra = 1
    fields = ['nome', 'wapi_token', 'wapi_instance', 'ativo']

    # Permissões abertas - o EmpresaAdmin já controla quem acessa qual empresa
    def has_add_permission(self, request, obj=None):
        return True

    def has_change_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return True

    def has_view_permission(self, request, obj=None):
        return True


class EmpresaUsuarioInline(admin.TabularInline):
    model = EmpresaUsuario
    extra = 1
    autocomplete_fields = ['usuario']


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    """Admin para gerenciar empresas"""
    list_display = ['nome', 'slug', 'dominio', 'plano', 'ativo', 'has_woo_config', 'created_at']
    list_filter = ['ativo', 'plano']
    search_fields = ['nome', 'slug', 'dominio']
    readonly_fields = ['created_at', 'updated_at', 'painel_acoes', 'chrome_api_key_display']
    inlines = [InstanciaWAPIInline, EmpresaUsuarioInline]

    def get_prepopulated_fields(self, request, obj=None):
        """Apenas superusers tem prepopulated_fields"""
        if request.user.is_superuser:
            return {'slug': ('nome',)}
        return {}

    def get_list_display(self, request):
        """Lista simplificada para usuarios normais"""
        if request.user.is_superuser:
            return ['nome', 'slug', 'dominio', 'plano', 'ativo', 'has_woo_config', 'created_at']
        return ['nome']

    def get_list_filter(self, request):
        """Sem filtros para usuarios normais"""
        if request.user.is_superuser:
            return ['ativo', 'plano']
        return []

    # Fieldsets completos para superusers
    fieldsets_superuser = (
        ('Identificacao', {
            'fields': ('nome', 'slug', 'dominio', 'ativo', 'plano', 'logo'),
            'description': 'A logo aparece na barra de cima do inbox.'
        }),
        ('Acoes', {
            'fields': ('painel_acoes',),
            'description': 'Acoes manuais para sincronizar dados e enviar mensagens.'
        }),
        ('WooCommerce - REST API', {
            'fields': ('woo_store_url', 'woo_consumer_key', 'woo_consumer_secret'),
            'description': 'API REST para sync diario de clientes e pedidos (roda as 9h). Gerar em WooCommerce > Settings > Advanced > REST API.'
        }),
        ('WooCommerce - SSH (Carrinhos/Leads)', {
            'fields': ('woo_ssh_host', 'woo_ssh_port', 'woo_ssh_user', 'woo_ssh_key_path'),
            'classes': ('collapse',),
            'description': 'Conexao SSH para importar carrinhos abandonados e leads (Form Vibes)'
        }),
        ('WooCommerce - Database', {
            'fields': ('woo_db_host', 'woo_db_port', 'woo_db_name',
                       'woo_db_user', 'woo_db_password', 'woo_table_prefix'),
            'classes': ('collapse',),
            'description': 'Credenciais do banco de dados MySQL do WooCommerce'
        }),
        ('WooCommerce - Webhook', {
            'fields': ('woo_webhook_secret',),
            'classes': ('collapse',),
            'description': 'Secret para validar webhooks. URL: /webhooks/woo/{slug}/order-created/'
        }),
        ('Form Vibes - Mapeamento de Campos', {
            'fields': ('fv_field_nome', 'fv_field_whatsapp', 'fv_field_tamanho'),
            'classes': ('collapse',),
            'description': 'Configure os nomes dos campos (meta_keys) do Form Vibes para esta empresa'
        }),
        ('W-API WhatsApp', {
            'fields': ('wapi_ativo', 'wapi_token', 'wapi_instance', 'wapi_telefone_monitoramento'),
            'description': 'Credenciais da W-API (w-api.app) para envio automático. Cada empresa tem suas próprias credenciais.'
        }),
        ('Mensagens WhatsApp', {
            'fields': (
                ('msg_ativa_lead', 'msg_whatsapp_lead', 'instancia_lead'),
                ('msg_ativa_lead_cliente', 'msg_whatsapp_lead_cliente', 'instancia_lead_cliente'),
                ('msg_ativa_cart', 'msg_whatsapp_cart', 'instancia_cart'),
                ('msg_ativa_pedido_novo', 'msg_whatsapp_pedido_novo', 'instancia_pedido_novo'),
                ('msg_ativa_pedido_processando', 'msg_whatsapp_pedido_processando', 'instancia_pedido_processando'),
                ('msg_ativa_pedido_embalado', 'msg_whatsapp_pedido_embalado', 'instancia_pedido_embalado'),
                ('msg_ativa_pedido_transito', 'msg_whatsapp_pedido_transito', 'instancia_pedido_transito'),
                ('msg_ativa_pedido_concluido', 'msg_whatsapp_pedido_concluido', 'instancia_pedido_concluido'),
                ('msg_ativa_pedido_cancelado', 'msg_whatsapp_pedido_cancelado', 'instancia_pedido_cancelado'),
            ),
            'description': 'Marque "Ativo" para habilitar cada mensagem. Use {nome}, {numero}, {valor}.'
        }),
        ('Bling API', {
            'fields': ('bling_client_id', 'bling_client_secret',
                        'bling_situacao_processando_id', 'bling_situacao_embalado_id',
                        'bling_situacao_transito_id', 'bling_situacao_concluido_id',
                        'bling_situacao_cancelado_id', 'bling_status_display',
                        'bling_logistica_id', 'msg_whatsapp_aguardando_retirada'),
            'classes': ('collapse',),
            'description': 'Credenciais Bling API V3. Configure os IDs das situações (use --list-situacoes para descobrir). Após configurar, acesse /bling/authorize/{slug}/ para autorizar.'
        }),
        ('Meta WhatsApp Business API', {
            'fields': ('meta_waba_id', 'meta_phone_number_id', 'meta_access_token',
                        'meta_template_transito', 'meta_webhook_verify_token',
                        'meta_whatsapp_humano',
                        'whatsapp_atendimento_oficial', 'meta_resposta_automatica'),
            'description': 'Cloud API oficial do WhatsApp (Meta). Templates precisam ser aprovados no WhatsApp Manager.'
        }),
        ('Meta Templates - Promocoes e Cupons', {
            'fields': (
                'meta_template_lead_cliente', 'meta_template_lead_nao_cliente',
                'meta_template_lead_nao_cliente_cupom',
                'meta_template_cart', 'meta_template_cliente_inativo',
                'meta_cupom_codigo', 'meta_cupom_desconto', 'meta_cupom_validade',
            ),
            'description': 'Templates Meta para envio diario de promocoes (leads do dia anterior e carrinhos abandonados). Cron roda as 10h.'
        }),
        ('Extensao Chrome - CRM WhatsApp', {
            'fields': ('chrome_api_key_display',),
            'description': 'Credenciais para configurar a extensão Chrome do WhatsApp Web → CRM.'
        }),
        ('Personalizacao', {
            'fields': ('timezone', 'cor_primaria'),
            'classes': ('collapse',),
        }),
        ('Datas', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    # Fieldsets limitados para usuarios normais
    fieldsets_user = (
        ('Informacoes da Empresa', {
            'fields': ('nome', 'logo'),
            'description': 'Informacoes basicas da sua empresa. A foto aparece na barra de cima do inbox — use a mesma do perfil do WhatsApp (quadrada, a partir de 200x200).'
        }),
        ('Acoes', {
            'fields': ('painel_acoes',),
            'description': 'Acoes manuais para sincronizar dados e enviar mensagens.'
        }),
        ('W-API WhatsApp', {
            'fields': ('wapi_ativo', 'wapi_token', 'wapi_instance'),
            'description': 'Configure suas credenciais da W-API (w-api.app) para envio automático de WhatsApp.'
        }),
        ('WooCommerce - REST API', {
            'fields': ('woo_store_url', 'woo_consumer_key', 'woo_consumer_secret'),
            'description': 'API REST para sync diario de clientes e pedidos. Gerar em WooCommerce > Settings > Advanced > REST API.'
        }),
        ('Webhook WooCommerce', {
            'fields': ('woo_webhook_secret',),
            'description': 'Secret para validar webhooks do WooCommerce. URL: /webhooks/woo/{slug}/order-created/'
        }),
        ('Mensagens WhatsApp', {
            'fields': (
                ('msg_ativa_lead', 'msg_whatsapp_lead', 'instancia_lead'),
                ('msg_ativa_lead_cliente', 'msg_whatsapp_lead_cliente', 'instancia_lead_cliente'),
                ('msg_ativa_cart', 'msg_whatsapp_cart', 'instancia_cart'),
                ('msg_ativa_pedido_novo', 'msg_whatsapp_pedido_novo', 'instancia_pedido_novo'),
                ('msg_ativa_pedido_processando', 'msg_whatsapp_pedido_processando', 'instancia_pedido_processando'),
                ('msg_ativa_pedido_embalado', 'msg_whatsapp_pedido_embalado', 'instancia_pedido_embalado'),
                ('msg_ativa_pedido_transito', 'msg_whatsapp_pedido_transito', 'instancia_pedido_transito'),
                ('msg_ativa_pedido_concluido', 'msg_whatsapp_pedido_concluido', 'instancia_pedido_concluido'),
                ('msg_ativa_pedido_cancelado', 'msg_whatsapp_pedido_cancelado', 'instancia_pedido_cancelado'),
            ),
            'description': 'Marque "Ativo" para habilitar cada mensagem. Use {nome}, {numero}, {valor}.'
        }),
        ('Bling API', {
            'fields': ('bling_client_id', 'bling_client_secret',
                        'bling_situacao_processando_id', 'bling_situacao_embalado_id',
                        'bling_situacao_transito_id', 'bling_situacao_concluido_id',
                        'bling_situacao_cancelado_id', 'bling_status_display',
                        'bling_logistica_id', 'msg_whatsapp_aguardando_retirada'),
            'classes': ('collapse',),
            'description': 'Credenciais Bling API V3. Configure os IDs das situações (use --list-situacoes para descobrir). Após configurar, acesse /bling/authorize/{slug}/ para autorizar.'
        }),
        ('Meta WhatsApp Business API', {
            'fields': ('meta_waba_id', 'meta_phone_number_id', 'meta_access_token',
                        'meta_template_transito', 'meta_webhook_verify_token',
                        'meta_whatsapp_humano',
                        'whatsapp_atendimento_oficial', 'meta_resposta_automatica'),
            'description': 'Cloud API oficial do WhatsApp (Meta). Templates precisam ser aprovados no WhatsApp Manager.'
        }),
        ('Meta Templates - Promocoes e Cupons', {
            'fields': (
                'meta_template_lead_cliente', 'meta_template_lead_nao_cliente',
                'meta_template_lead_nao_cliente_cupom',
                'meta_template_cart', 'meta_template_cliente_inativo',
                'meta_cupom_codigo', 'meta_cupom_desconto', 'meta_cupom_validade',
            ),
            'description': 'Templates Meta para envio diario de promocoes (leads do dia anterior e carrinhos abandonados). Cron roda as 10h.'
        }),
        ('Extensao Chrome - CRM WhatsApp', {
            'fields': ('chrome_api_key_display',),
            'description': 'Credenciais para configurar a extensão Chrome do WhatsApp Web → CRM.'
        }),
    )

    def get_fieldsets(self, request, obj=None):
        """Retorna fieldsets baseado no tipo de usuario"""
        if request.user.is_superuser:
            return self.fieldsets_superuser
        return self.fieldsets_user

    def get_readonly_fields(self, request, obj=None):
        """Usuarios normais so podem editar mensagens WhatsApp"""
        if request.user.is_superuser:
            return ['created_at', 'updated_at', 'bling_status_display', 'painel_acoes', 'chrome_api_key_display']
        # Usuarios normais: nome eh readonly
        return ['nome', 'created_at', 'updated_at', 'bling_status_display', 'painel_acoes', 'chrome_api_key_display']

    def painel_acoes(self, obj):
        """Botoes de acao dentro da pagina da empresa."""
        if not obj or not obj.pk:
            return '-'

        sync_url = reverse('admin:tenants_empresa_sync_woo', args=[obj.pk])
        promo_url = reverse('admin:tenants_empresa_enviar_promo', args=[obj.pk])
        ssh_url = reverse('admin:tenants_empresa_import_ssh', args=[obj.pk])
        cupom_url = reverse('admin:tenants_empresa_cupom_cliente', args=[obj.pk])
        brevo_url = reverse('admin:tenants_empresa_exportar_brevo', args=[obj.pk])

        btns = '<div style="display:flex; flex-wrap:wrap; gap:8px;">'

        # Botao Import SSH (Carrinhos + Leads)
        has_ssh = getattr(obj, 'has_woocommerce_config', False)
        if has_ssh:
            btns += (
                f'<a href="{ssh_url}" class="button" '
                f'style="background:#e67e22; color:white; padding:6px 15px;">'
                f'Import SSH (Carrinhos + Leads)</a>'
            )
        else:
            btns += (
                '<span style="color:gray;">'
                'Import SSH: configure SSH/DB primeiro</span>'
            )

        # Botao Sync WooCommerce
        if obj.has_woocommerce_api:
            btns += (
                f'<a href="{sync_url}" class="button" '
                f'style="background:#417690; color:white; padding:6px 15px;">'
                f'Sync WooCommerce (Clientes + Pedidos)</a>'
            )
        else:
            btns += (
                '<span style="color:gray;">'
                'Sync WooCommerce: configure Consumer Key/Secret primeiro</span>'
            )

        # Botao Enviar Promocoes
        if obj.meta_phone_number_id and obj.meta_access_token:
            btns += (
                f'<a href="{promo_url}" class="button" '
                f'style="background:#28a745; color:white; padding:6px 15px;">'
                f'Enviar Promocoes Agora</a>'
            )
        else:
            btns += (
                '<span style="color:gray;">'
                'Enviar Promocoes: configure Meta WhatsApp primeiro</span>'
            )

        # Botao Verificar e enviar cupom cliente (Leads + Carrinhos)
        if obj.meta_phone_number_id and obj.meta_access_token:
            btns += (
                f'<a href="{cupom_url}" class="button" '
                f'style="background:#8e44ad; color:white; padding:6px 15px;">'
                f'Verificar e enviar cupom (Leads + Carrinhos)</a>'
            )
        else:
            btns += (
                '<span style="color:gray;">'
                'Cupom cliente: configure Meta WhatsApp primeiro</span>'
            )

        # Botoes Exportar Brevo (CSV p/ email marketing) — compradores e nao
        btns += (
            f'<a href="{brevo_url}?tipo=compradores" class="button" '
            f'style="background:#0a66c2; color:white; padding:6px 15px;">'
            f'Exportar Brevo: Compradores (CSV)</a>'
        )
        btns += (
            f'<a href="{brevo_url}?tipo=nao-compradores" class="button" '
            f'style="background:#5b8def; color:white; padding:6px 15px;">'
            f'Exportar Brevo: Nao-compradores (CSV)</a>'
        )
        btns += (
            f'<a href="{brevo_url}?tipo=todos" class="button" '
            f'style="background:#34495e; color:white; padding:6px 15px;">'
            f'Exportar Brevo: Todos (CSV)</a>'
        )

        btns += '</div>'
        return format_html(btns)
    painel_acoes.short_description = 'Acoes'

    def get_urls(self):
        """Adiciona URLs customizadas para acoes da empresa."""
        custom_urls = [
            path(
                '<int:empresa_id>/import-ssh/',
                self.admin_site.admin_view(self.view_import_ssh),
                name='tenants_empresa_import_ssh',
            ),
            path(
                '<int:empresa_id>/sync-woo/',
                self.admin_site.admin_view(self.view_sync_woo),
                name='tenants_empresa_sync_woo',
            ),
            path(
                '<int:empresa_id>/enviar-promo/',
                self.admin_site.admin_view(self.view_enviar_promo),
                name='tenants_empresa_enviar_promo',
            ),
            path(
                '<int:empresa_id>/cupom-cliente/',
                self.admin_site.admin_view(self.view_cupom_cliente),
                name='tenants_empresa_cupom_cliente',
            ),
            path(
                '<int:empresa_id>/cupom-cliente/iniciar/',
                self.admin_site.admin_view(self.view_cupom_cliente_iniciar),
                name='tenants_empresa_cupom_cliente_iniciar',
            ),
            path(
                '<int:empresa_id>/cupom-cliente/progresso/',
                self.admin_site.admin_view(self.view_cupom_cliente_progresso),
                name='tenants_empresa_cupom_cliente_progresso',
            ),
            path(
                '<int:empresa_id>/exportar-brevo/',
                self.admin_site.admin_view(self.view_exportar_brevo),
                name='tenants_empresa_exportar_brevo',
            ),
        ]
        return custom_urls + super().get_urls()

    def view_exportar_brevo(self, request, empresa_id):
        """
        Gera e baixa o CSV de contatos no formato Brevo.
        Query params:
          tipo=compradores | nao-compradores | todos  (default: todos)
          sem_email=1  -> inclui quem nao tem email (default: so com email)
          incluir_leads=1 -> inclui Leads (so faz efeito com sem_email=1)
        """
        from django.http import HttpResponse
        from customers.services.exportar_brevo import coletar, gerar_csv_texto

        empresa = Empresa.objects.get(pk=empresa_id)
        tipo = request.GET.get('tipo', 'todos')
        exige_email = request.GET.get('sem_email') != '1'
        incluir_leads = request.GET.get('incluir_leads') == '1'

        res = coletar(empresa, incluir_leads=incluir_leads, exige_email=exige_email)
        if tipo == 'compradores':
            linhas = res['compradores']
        elif tipo == 'nao-compradores':
            linhas = res['nao_compradores']
        else:
            linhas = res['compradores'] + res['nao_compradores']

        if not linhas:
            messages.warning(
                request,
                f'{empresa.nome}: nenhum contato em "{tipo}" '
                f'{"com email" if exige_email else ""}. '
                f'({res["sem_email_pulados"]} sem email)'
            )
            return HttpResponseRedirect(
                reverse('admin:tenants_empresa_change', args=[empresa_id])
            )

        csv_texto = gerar_csv_texto(linhas)
        resp = HttpResponse(csv_texto, content_type='text/csv; charset=utf-8')
        nome = f'brevo_{empresa.slug}_{tipo}.csv'
        resp['Content-Disposition'] = f'attachment; filename="{nome}"'
        return resp

    def view_import_ssh(self, request, empresa_id):
        """View: import carrinhos + leads via SSH."""
        from django.core.management import call_command
        from io import StringIO
        from datetime import datetime, timedelta

        empresa = Empresa.objects.get(pk=empresa_id)
        redirect_url = reverse('admin:tenants_empresa_change', args=[empresa_id])

        if not getattr(empresa, 'has_woocommerce_config', False):
            messages.warning(request, f'{empresa.nome}: SSH/Database nao configurado')
            return HttpResponseRedirect(redirect_url)

        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')

        resultados = []

        # Import carrinhos e pedidos
        try:
            out = StringIO()
            call_command(
                'import_customers',
                empresa=empresa.slug,
                start_date=start_str,
                end_date=end_str,
                import_type='all',
                stdout=out,
                verbosity=1,
            )
            resultados.append('Carrinhos/Pedidos: OK')
        except Exception as e:
            resultados.append(f'Carrinhos/Pedidos: Erro - {e}')

        # Import leads
        try:
            out = StringIO()
            call_command(
                'import_leads',
                empresa=empresa.slug,
                start_date=start_str,
                end_date=end_str,
                stdout=out,
                verbosity=1,
            )
            resultados.append('Leads: OK')
        except Exception as e:
            resultados.append(f'Leads: Erro - {e}')

        msg = f'{empresa.nome} (ultimos 7 dias): ' + ' | '.join(resultados)
        if all('OK' in r for r in resultados):
            messages.success(request, msg)
        else:
            messages.warning(request, msg)

        return HttpResponseRedirect(redirect_url)

    def view_sync_woo(self, request, empresa_id):
        """View: sync WooCommerce clientes + pedidos."""
        from customers.services.woocommerce import sync_customers, sync_orders

        empresa = Empresa.objects.get(pk=empresa_id)
        redirect_url = reverse('admin:tenants_empresa_change', args=[empresa_id])

        if not empresa.has_woocommerce_api:
            messages.warning(request, f'{empresa.nome}: WooCommerce API nao configurado')
            return HttpResponseRedirect(redirect_url)

        try:
            stats_c = sync_customers(empresa)
            stats_o = sync_orders(empresa, days_back=7)
            messages.success(
                request,
                f'{empresa.nome}: {stats_c["total"]} clientes ({stats_c["criados"]} novos), '
                f'{stats_o["total"]} pedidos ({stats_o["criados"]} novos)'
            )
        except Exception as e:
            messages.error(request, f'{empresa.nome}: Erro - {e}')

        return HttpResponseRedirect(redirect_url)

    def view_enviar_promo(self, request, empresa_id):
        """View: enviar promocoes (leads + carrinhos + inativos)."""
        from customers.tasks import (
            _processar_leads_dia_anterior,
            _processar_carts_dia_anterior,
            _processar_clientes_inativos,
        )

        empresa = Empresa.objects.get(pk=empresa_id)
        redirect_url = reverse('admin:tenants_empresa_change', args=[empresa_id])

        if not empresa.meta_phone_number_id or not empresa.meta_access_token:
            messages.warning(request, f'{empresa.nome}: Meta WhatsApp nao configurado')
            return HttpResponseRedirect(redirect_url)

        leads = _processar_leads_dia_anterior(empresa)
        carts = _processar_carts_dia_anterior(empresa)
        inativos = _processar_clientes_inativos(empresa)

        messages.success(
            request,
            f'{empresa.nome}: {leads} leads, {carts} carrinhos, {inativos} inativos enviados'
        )

        return HttpResponseRedirect(redirect_url)

    def view_cupom_cliente(self, request, empresa_id):
        """
        Pagina leve do cupom cliente. NAO faz verificacao no request (evita
        timeout/502): a verificacao (preview) e o envio rodam no Celery, e a
        barra de % acompanha via polling do endpoint /progresso/.
        """
        from django.template.response import TemplateResponse

        empresa = Empresa.objects.get(pk=empresa_id)
        redirect_url = reverse('admin:tenants_empresa_change', args=[empresa_id])

        if not empresa.meta_phone_number_id or not empresa.meta_access_token:
            messages.warning(request, f'{empresa.nome}: Meta WhatsApp nao configurado')
            return HttpResponseRedirect(redirect_url)

        context = {
            **self.admin_site.each_context(request),
            'title': f'Enviar cupom cliente - {empresa.nome}',
            'empresa': empresa,
            'iniciar_url': reverse('admin:tenants_empresa_cupom_cliente_iniciar', args=[empresa_id]),
            'progresso_url': reverse('admin:tenants_empresa_cupom_cliente_progresso', args=[empresa_id]),
            'voltar_url': redirect_url,
        }
        return TemplateResponse(request, 'admin/tenants/cupom_cliente.html', context)

    def view_cupom_cliente_iniciar(self, request, empresa_id):
        """
        Dispara a task Celery (POST). ?fase=preview verifica e conta; ?fase=envio
        verifica e envia. Datas opcionais via querystring. Retorna JSON.
        """
        from django.http import JsonResponse
        from django.core.cache import cache
        from customers.tasks import cupom_cliente_task, cupom_cache_key

        if request.method != 'POST':
            return JsonResponse({'ok': False, 'error': 'metodo invalido'}, status=405)

        empresa = Empresa.objects.get(pk=empresa_id)
        if not empresa.meta_phone_number_id or not empresa.meta_access_token:
            return JsonResponse({'ok': False, 'error': 'Meta WhatsApp nao configurado'}, status=400)

        fase = request.GET.get('fase', 'preview')
        dry_run = fase != 'envio'

        atual = cache.get(cupom_cache_key(empresa_id, fase))
        if atual and atual.get('status') == 'running':
            return JsonResponse({'ok': True, 'status': 'running'})

        data_inicio = request.GET.get('data_inicio') or None
        data_fim = request.GET.get('data_fim') or None
        cupom_cliente_task.delay(
            empresa_id, alvo='ambos', dry_run=dry_run,
            data_inicio=data_inicio, data_fim=data_fim,
        )
        return JsonResponse({'ok': True, 'status': 'started', 'fase': fase})

    def view_cupom_cliente_progresso(self, request, empresa_id):
        """Retorna o progresso (%) da fase pedida (?fase=preview|envio)."""
        from django.http import JsonResponse
        from django.core.cache import cache
        from customers.tasks import cupom_cache_key

        fase = request.GET.get('fase', 'preview')
        data = cache.get(cupom_cache_key(empresa_id, fase))
        if not data:
            return JsonResponse({'status': 'idle', 'fase': fase, 'percent': 0})
        return JsonResponse(data)

    def get_queryset(self, request):
        """Usuarios normais so veem sua propria empresa"""
        qs = super().get_queryset(request)
        if not request.user.is_authenticated:
            return qs.none()
        if request.user.is_superuser:
            return qs
        # Filtrar apenas empresas do usuario
        return qs.filter(usuarios__usuario=request.user)

    def get_inlines(self, request, obj=None):
        """Superusers veem tudo, usuarios normais veem instancias WAPI"""
        if request.user.is_superuser:
            return [InstanciaWAPIInline, EmpresaUsuarioInline]
        return [InstanciaWAPIInline]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Filtra instâncias W-API para mostrar apenas as da empresa sendo editada"""
        if db_field.name.startswith('instancia_'):
            obj_id = request.resolver_match.kwargs.get('object_id')
            if obj_id:
                kwargs['queryset'] = InstanciaWAPI.objects.filter(empresa_id=obj_id, ativo=True)
            else:
                kwargs['queryset'] = InstanciaWAPI.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    actions = ['sync_bling_agora', 'sync_woocommerce_agora', 'enviar_promocoes_agora']

    def has_woo_config(self, obj):
        return obj.has_woocommerce_config
    has_woo_config.boolean = True
    has_woo_config.short_description = 'WooCommerce'

    def chrome_api_key_display(self, obj):
        """Mostra a API key da extensão Chrome (calculada a partir do slug + webhook secret)."""
        if not obj or not obj.pk:
            return '-'
        if not obj.woo_webhook_secret:
            return format_html('<span style="color:gray;">Configure o woo_webhook_secret primeiro</span>')
        api_key = hashlib.sha256(
            f"{obj.slug}:{obj.woo_webhook_secret}".encode()
        ).hexdigest()[:32]
        return format_html(
            '<code style="font-size:14px; background:#f0f0f0; padding:4px 8px; '
            'border-radius:4px; user-select:all;">{}</code>'
            '<br><small style="color:#666;">URL: https://leads.posvendafacil.com.br &nbsp;|&nbsp; Slug: {}</small>',
            api_key, obj.slug
        )
    chrome_api_key_display.short_description = 'API Key Extensão Chrome'

    def bling_status_display(self, obj):
        """Mostra status da conexão Bling e link para autorizar."""
        if not obj.bling_client_id:
            return format_html('<span style="color:gray;">Não configurado</span>')
        try:
            token = obj.bling_token
            if token.is_expired:
                status = '<span style="color:red;">Token expirado</span>'
            else:
                status = '<span style="color:green;">Conectado</span>'
        except Exception:
            status = '<span style="color:orange;">Não autorizado</span>'
        authorize_url = f'/bling/authorize/{obj.slug}/'
        return format_html(f'{status} &nbsp; <a href="{authorize_url}" class="button">Autorizar Bling</a>')
    bling_status_display.short_description = 'Status Bling'

    def sync_bling_agora(self, request, queryset):
        """Action: sincronizar pedidos de todos os status configurados no Bling."""
        from bling.tasks import sync_empresa_pedidos_por_status, BLING_STATUS_MAP
        for empresa in queryset:
            if not empresa.bling_client_id:
                self.message_user(request, f"{empresa.nome}: Bling não configurado", messages.WARNING)
                continue

            total_enviados = 0
            total_erros = 0
            status_processados = []

            for status, config in BLING_STATUS_MAP.items():
                sit_id = getattr(empresa, config['campo_situacao'], '')
                if not sit_id:
                    continue
                try:
                    stats = sync_empresa_pedidos_por_status(empresa, status)
                    total_enviados += stats['enviados']
                    total_erros += stats['erros']
                    if stats['total'] > 0:
                        status_processados.append(f"{status}: {stats['enviados']}/{stats['total']}")
                except Exception as e:
                    total_erros += 1
                    self.message_user(request, f"{empresa.nome} [{status}]: Erro - {e}", messages.ERROR)

            if status_processados:
                detail = " | ".join(status_processados)
                self.message_user(
                    request,
                    f"{empresa.nome}: {total_enviados} enviados ({detail})",
                    messages.SUCCESS if total_erros == 0 else messages.WARNING
                )
            else:
                self.message_user(request, f"{empresa.nome}: Nenhum status configurado no Bling", messages.WARNING)
    sync_bling_agora.short_description = 'Sincronizar Bling (todos status)'

    def sync_woocommerce_agora(self, request, queryset):
        """Action: sincronizar clientes e pedidos do WooCommerce via API REST."""
        from customers.services.woocommerce import sync_customers, sync_orders

        for empresa in queryset:
            if not empresa.has_woocommerce_api:
                self.message_user(request, f"{empresa.nome}: WooCommerce API nao configurado", messages.WARNING)
                continue

            try:
                stats_c = sync_customers(empresa)
                stats_o = sync_orders(empresa, days_back=7)
                self.message_user(
                    request,
                    f"{empresa.nome}: {stats_c['total']} clientes ({stats_c['criados']} novos), "
                    f"{stats_o['total']} pedidos ({stats_o['criados']} novos)",
                    messages.SUCCESS
                )
            except Exception as e:
                self.message_user(request, f"{empresa.nome}: Erro - {e}", messages.ERROR)
    sync_woocommerce_agora.short_description = 'Sync WooCommerce (clientes + pedidos)'

    def enviar_promocoes_agora(self, request, queryset):
        """Action: rodar envio de promocoes (leads + carrinhos + inativos) agora."""
        from customers.tasks import (
            _processar_leads_dia_anterior,
            _processar_carts_dia_anterior,
            _processar_clientes_inativos,
        )

        for empresa in queryset:
            if not empresa.meta_phone_number_id or not empresa.meta_access_token:
                self.message_user(request, f"{empresa.nome}: Meta WhatsApp nao configurado", messages.WARNING)
                continue

            leads = _processar_leads_dia_anterior(empresa)
            carts = _processar_carts_dia_anterior(empresa)
            inativos = _processar_clientes_inativos(empresa)

            self.message_user(
                request,
                f"{empresa.nome}: {leads} leads, {carts} carrinhos, {inativos} inativos enviados",
                messages.SUCCESS
            )
    enviar_promocoes_agora.short_description = 'Enviar Promocoes Agora (leads + carrinhos + inativos)'

    def has_module_permission(self, request):
        """Superusers ou usuarios vinculados a alguma empresa"""
        if not request.user.is_authenticated:
            return True  # Permitir acesso a pagina de login
        if request.user.is_superuser:
            return True
        return EmpresaUsuario.objects.filter(usuario=request.user).exists()

    def has_view_permission(self, request, obj=None):
        if not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if obj is None:
            return EmpresaUsuario.objects.filter(usuario=request.user).exists()
        return EmpresaUsuario.objects.filter(usuario=request.user, empresa=obj).exists()

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        if not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if obj is None:
            return EmpresaUsuario.objects.filter(usuario=request.user).exists()
        return EmpresaUsuario.objects.filter(usuario=request.user, empresa=obj).exists()

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(EmpresaUsuario)
class EmpresaUsuarioAdmin(admin.ModelAdmin):
    """Admin para vincular usuarios a empresas"""
    list_display = ['usuario', 'empresa', 'role', 'is_default', 'created_at']
    list_filter = ['empresa', 'role', 'is_default']
    search_fields = ['usuario__username', 'usuario__email', 'empresa__nome']
    autocomplete_fields = ['usuario', 'empresa']
    readonly_fields = ['created_at']

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
