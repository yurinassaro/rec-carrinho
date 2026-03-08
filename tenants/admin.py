from django.contrib import admin, messages
from django.contrib.auth.models import User
from django.utils.html import format_html
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
    readonly_fields = ['created_at', 'updated_at']
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
            'fields': ('nome', 'slug', 'dominio', 'ativo', 'plano')
        }),
        ('WooCommerce - SSH', {
            'fields': ('woo_ssh_host', 'woo_ssh_port', 'woo_ssh_user', 'woo_ssh_key_path'),
            'classes': ('collapse',),
            'description': 'Configuracoes de conexao SSH para acessar o servidor WooCommerce'
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
            'fields': ('wapi_ativo', 'wapi_token', 'wapi_instance'),
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
                        'bling_situacao_cancelado_id', 'bling_status_display'),
            'classes': ('collapse',),
            'description': 'Credenciais Bling API V3. Configure os IDs das situações (use --list-situacoes para descobrir). Após configurar, acesse /bling/authorize/{slug}/ para autorizar.'
        }),
        ('Meta WhatsApp Business API', {
            'fields': ('meta_waba_id', 'meta_phone_number_id', 'meta_access_token',
                        'meta_template_transito', 'meta_webhook_verify_token',
                        'meta_whatsapp_humano'),
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
        ('Personalizacao', {
            'fields': ('timezone', 'logo', 'cor_primaria'),
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
            'fields': ('nome',),
            'description': 'Informacoes basicas da sua empresa'
        }),
        ('W-API WhatsApp', {
            'fields': ('wapi_ativo', 'wapi_token', 'wapi_instance'),
            'description': 'Configure suas credenciais da W-API (w-api.app) para envio automático de WhatsApp.'
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
                        'bling_situacao_cancelado_id', 'bling_status_display'),
            'classes': ('collapse',),
            'description': 'Credenciais Bling API V3. Configure os IDs das situações (use --list-situacoes para descobrir). Após configurar, acesse /bling/authorize/{slug}/ para autorizar.'
        }),
        ('Meta WhatsApp Business API', {
            'fields': ('meta_waba_id', 'meta_phone_number_id', 'meta_access_token',
                        'meta_template_transito', 'meta_webhook_verify_token',
                        'meta_whatsapp_humano'),
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
    )

    def get_fieldsets(self, request, obj=None):
        """Retorna fieldsets baseado no tipo de usuario"""
        if request.user.is_superuser:
            return self.fieldsets_superuser
        return self.fieldsets_user

    def get_readonly_fields(self, request, obj=None):
        """Usuarios normais so podem editar mensagens WhatsApp"""
        if request.user.is_superuser:
            return ['created_at', 'updated_at', 'bling_status_display']
        # Usuarios normais: nome eh readonly
        return ['nome', 'created_at', 'updated_at', 'bling_status_display']

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

    actions = ['sync_bling_agora']

    def has_woo_config(self, obj):
        return obj.has_woocommerce_config
    has_woo_config.boolean = True
    has_woo_config.short_description = 'WooCommerce'

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
