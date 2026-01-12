from django.contrib import admin
from django.contrib.auth.models import User
from .models import Empresa, EmpresaUsuario


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


class EmpresaUsuarioInline(admin.TabularInline):
    model = EmpresaUsuario
    extra = 1
    autocomplete_fields = ['usuario']


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    """Admin para gerenciar empresas (apenas superusers)"""
    list_display = ['nome', 'slug', 'dominio', 'plano', 'ativo', 'has_woo_config', 'created_at']
    list_filter = ['ativo', 'plano']
    search_fields = ['nome', 'slug', 'dominio']
    prepopulated_fields = {'slug': ('nome',)}
    readonly_fields = ['created_at', 'updated_at']
    inlines = [EmpresaUsuarioInline]

    fieldsets = (
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
        ('Form Vibes - Mapeamento de Campos', {
            'fields': ('fv_field_nome', 'fv_field_whatsapp', 'fv_field_tamanho'),
            'classes': ('collapse',),
            'description': 'Configure os nomes dos campos (meta_keys) do Form Vibes para esta empresa'
        }),
        ('Mensagens WhatsApp', {
            'fields': ('msg_whatsapp_lead', 'msg_whatsapp_cart'),
            'description': 'Configure as mensagens padrão do WhatsApp. Use {nome} para inserir o nome do cliente.'
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

    def has_woo_config(self, obj):
        return obj.has_woocommerce_config
    has_woo_config.boolean = True
    has_woo_config.short_description = 'WooCommerce'

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
