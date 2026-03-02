import re
from django.contrib import admin
from import_export import resources, fields
from import_export.admin import ExportMixin
from tenants.admin import TenantAdminMixin
from .models import CarrinhoAbandonado, LeadNaoComprador, Comprador


def format_phone(phone_raw):
    """Formata telefone para Meta Ads: apenas digitos com codigo 55"""
    if not phone_raw:
        return ''
    phone = re.sub(r'\D', '', str(phone_raw))
    if len(phone) < 10:
        return ''
    if not phone.startswith('55'):
        phone = f'55{phone}'
    return phone


def clean_postcode(postcode):
    """Remove caracteres nao-numericos do CEP"""
    if not postcode:
        return ''
    return re.sub(r'\D', '', str(postcode))


# ─── Resources (django-import-export) ────────────────────────────────

class CarrinhoAbandonadoResource(resources.ModelResource):
    phone = fields.Field(column_name='phone')
    email = fields.Field(column_name='email')
    fn = fields.Field(column_name='fn')
    ln = fields.Field(column_name='ln')
    ct = fields.Field(column_name='ct')
    st = fields.Field(column_name='st')
    zip = fields.Field(column_name='zip')
    country = fields.Field(column_name='country')
    value = fields.Field(column_name='value')

    class Meta:
        model = CarrinhoAbandonado
        fields = ('phone', 'email', 'fn', 'ln', 'ct', 'st', 'zip', 'country', 'value')
        export_order = ('phone', 'email', 'fn', 'ln', 'ct', 'st', 'zip', 'country', 'value')

    def dehydrate_phone(self, cart):
        return format_phone(cart.customer.phone)

    def dehydrate_email(self, cart):
        return cart.customer.email or ''

    def dehydrate_fn(self, cart):
        return cart.customer.first_name or ''

    def dehydrate_ln(self, cart):
        return cart.customer.last_name or ''

    def dehydrate_ct(self, cart):
        return cart.customer.billing_city or ''

    def dehydrate_st(self, cart):
        return cart.customer.billing_state or ''

    def dehydrate_zip(self, cart):
        return clean_postcode(cart.customer.billing_postcode)

    def dehydrate_country(self, cart):
        return 'BR'

    def dehydrate_value(self, cart):
        return str(cart.cart_total or '')


class LeadNaoCompradorResource(resources.ModelResource):
    phone = fields.Field(column_name='phone')
    fn = fields.Field(column_name='fn')

    class Meta:
        model = LeadNaoComprador
        fields = ('phone', 'fn')
        export_order = ('phone', 'fn')

    def dehydrate_phone(self, lead):
        return format_phone(lead.whatsapp)

    def dehydrate_fn(self, lead):
        first = (lead.nome or '').split()[0] if lead.nome else ''
        return first


class CompradorResource(resources.ModelResource):
    phone = fields.Field(column_name='phone')
    email = fields.Field(column_name='email')
    fn = fields.Field(column_name='fn')
    ln = fields.Field(column_name='ln')
    ct = fields.Field(column_name='ct')
    st = fields.Field(column_name='st')
    zip = fields.Field(column_name='zip')
    country = fields.Field(column_name='country')
    value = fields.Field(column_name='value')

    class Meta:
        model = Comprador
        fields = ('phone', 'email', 'fn', 'ln', 'ct', 'st', 'zip', 'country', 'value')
        export_order = ('phone', 'email', 'fn', 'ln', 'ct', 'st', 'zip', 'country', 'value')

    def dehydrate_phone(self, customer):
        return format_phone(customer.phone)

    def dehydrate_email(self, customer):
        return customer.email or ''

    def dehydrate_fn(self, customer):
        return customer.first_name or ''

    def dehydrate_ln(self, customer):
        return customer.last_name or ''

    def dehydrate_ct(self, customer):
        return customer.billing_city or ''

    def dehydrate_st(self, customer):
        return customer.billing_state or ''

    def dehydrate_zip(self, customer):
        return clean_postcode(customer.billing_postcode)

    def dehydrate_country(self, customer):
        return 'BR'

    def dehydrate_value(self, customer):
        return str(customer.total_spent or '')


# ─── Admin classes ────────────────────────────────────────────────────

@admin.register(CarrinhoAbandonado)
class CarrinhoAbandonadoAdmin(TenantAdminMixin, ExportMixin, admin.ModelAdmin):
    resource_class = CarrinhoAbandonadoResource

    list_display = [
        'get_email', 'get_phone', 'get_name', 'cart_total',
        'get_city', 'get_state', 'created_at',
    ]
    list_filter = ['created_at', 'empresa']
    search_fields = ['customer__email', 'customer__phone', 'customer__first_name']
    ordering = ['-created_at']

    def get_email(self, obj):
        return obj.customer.email
    get_email.short_description = 'Email'

    def get_phone(self, obj):
        return format_phone(obj.customer.phone)
    get_phone.short_description = 'Telefone'

    def get_name(self, obj):
        return obj.customer.full_name
    get_name.short_description = 'Nome'

    def get_city(self, obj):
        return obj.customer.billing_city or '-'
    get_city.short_description = 'Cidade'

    def get_state(self, obj):
        return obj.customer.billing_state or '-'
    get_state.short_description = 'UF'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LeadNaoComprador)
class LeadNaoCompradorAdmin(TenantAdminMixin, ExportMixin, admin.ModelAdmin):
    resource_class = LeadNaoCompradorResource

    list_display = [
        'nome', 'get_phone', 'numero_sapato', 'status', 'created_at',
    ]
    list_filter = ['created_at', 'empresa']
    search_fields = ['nome', 'whatsapp']
    ordering = ['-created_at']

    def get_phone(self, obj):
        return format_phone(obj.whatsapp)
    get_phone.short_description = 'Telefone'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Comprador)
class CompradorAdmin(TenantAdminMixin, ExportMixin, admin.ModelAdmin):
    resource_class = CompradorResource

    list_display = [
        'email', 'get_phone', 'full_name', 'total_spent',
        'completed_orders', 'billing_city', 'billing_state',
    ]
    list_filter = ['status', 'empresa']
    search_fields = ['email', 'phone', 'first_name', 'last_name']
    ordering = ['-total_spent']

    def get_phone(self, obj):
        return format_phone(obj.phone)
    get_phone.short_description = 'Telefone'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
