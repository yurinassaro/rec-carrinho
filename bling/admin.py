from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse

from .models import BlingToken, BlingPedidoEnviado


@admin.register(BlingToken)
class BlingTokenAdmin(admin.ModelAdmin):
    list_display = ['empresa', 'expires_at', 'token_status', 'updated_at']
    readonly_fields = ['empresa', 'expires_at', 'updated_at']

    def token_status(self, obj):
        if obj.is_expired:
            return format_html('<span style="color:red;">Expirado</span>')
        return format_html('<span style="color:green;">Válido</span>')
    token_status.short_description = 'Status'

    def has_add_permission(self, request):
        return False


@admin.register(BlingPedidoEnviado)
class BlingPedidoEnviadoAdmin(admin.ModelAdmin):
    list_display = ['numero_pedido', 'empresa', 'nome_cliente', 'telefone', 'canal', 'enviado_em']
    list_filter = ['empresa', 'canal', 'enviado_em']
    search_fields = ['numero_pedido', 'nome_cliente', 'telefone', 'bling_pedido_id']
    readonly_fields = ['empresa', 'bling_pedido_id', 'numero_pedido', 'telefone',
                       'nome_cliente', 'canal', 'enviado_em']
    ordering = ['-enviado_em']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
