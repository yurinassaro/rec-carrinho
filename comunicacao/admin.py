from django.contrib import admin
from django.utils.html import format_html
from comunicacao.models import (
    RegraComunicacao, ContatoBlacklist, FilaEnvio, EventoRecebido,
)


@admin.register(RegraComunicacao)
class RegraComunicacaoAdmin(admin.ModelAdmin):
    list_display = [
        'nome', 'gatilho', 'etapa', 'canal', 'ativo_badge',
        'prioridade', 'stats_display', 'updated_at',
    ]
    list_filter = ['empresa', 'gatilho', 'ativo', 'canal']
    list_editable = ['prioridade']
    search_fields = ['nome', 'template_meta']
    ordering = ['empresa', 'gatilho', 'etapa']

    fieldsets = (
        ('Identificação', {
            'fields': ('empresa', 'nome', 'descricao', 'gatilho', 'ativo', 'prioridade', 'etapa'),
        }),
        ('Timing', {
            'fields': ('delay_horas', 'horario_inicio', 'horario_fim', 'dias_semana'),
        }),
        ('Frequency Capping', {
            'fields': (
                'cooldown_horas', 'max_msgs_semana_telefone',
                'max_envios_total', 'max_envios_dia', 'max_ignorados_consecutivos',
            ),
        }),
        ('Condições Extras', {
            'fields': ('condicoes',),
            'classes': ('collapse',),
            'description': 'JSON com filtros extras. Ex: {"min_cart_value": 50, "min_orders": 1}',
        }),
        ('Template / Mensagem', {
            'fields': (
                'canal', 'template_meta', 'template_params_map',
                'texto_wapi', 'button_url_param', 'instancia_wapi',
            ),
        }),
        ('Cupom', {
            'fields': ('usar_cupom', 'cupom_codigo', 'cupom_desconto', 'cupom_validade'),
            'classes': ('collapse',),
        }),
        ('Estatísticas', {
            'fields': (
                'total_enviados', 'total_entregues', 'total_lidos',
                'total_respondidos', 'total_convertidos',
            ),
            'classes': ('collapse',),
        }),
    )

    readonly_fields = [
        'total_enviados', 'total_entregues', 'total_lidos',
        'total_respondidos', 'total_convertidos',
    ]

    def ativo_badge(self, obj):
        if obj.ativo:
            return format_html('<span style="color: green; font-weight: bold;">●</span> Ativo')
        return format_html('<span style="color: red;">●</span> Inativo')
    ativo_badge.short_description = 'Status'

    def stats_display(self, obj):
        if obj.total_enviados == 0:
            return '—'
        taxa_leitura = round(obj.total_lidos / obj.total_enviados * 100) if obj.total_enviados else 0
        taxa_resposta = round(obj.total_respondidos / obj.total_enviados * 100) if obj.total_enviados else 0
        return format_html(
            '📤{} 📖{}% 💬{}%',
            obj.total_enviados, taxa_leitura, taxa_resposta,
        )
    stats_display.short_description = 'Enviados / Leitura / Resposta'


@admin.register(ContatoBlacklist)
class ContatoBlacklistAdmin(admin.ModelAdmin):
    list_display = ['telefone', 'empresa', 'motivo', 'detalhes_curto', 'created_at']
    list_filter = ['empresa', 'motivo']
    search_fields = ['telefone']
    readonly_fields = ['created_at']

    def detalhes_curto(self, obj):
        return obj.detalhes[:80] if obj.detalhes else '—'
    detalhes_curto.short_description = 'Detalhes'


@admin.register(FilaEnvio)
class FilaEnvioAdmin(admin.ModelAdmin):
    list_display = [
        'telefone', 'nome', 'regra_nome', 'status_badge',
        'agendar_para', 'processado_em',
    ]
    list_filter = ['empresa', 'status', 'regra__gatilho']
    search_fields = ['telefone', 'nome']
    readonly_fields = [
        'empresa', 'regra', 'telefone', 'nome', 'lead', 'cart', 'customer',
        'agendar_para', 'status', 'mensagem', 'erro', 'created_at', 'processado_em',
    ]
    ordering = ['-created_at']

    def regra_nome(self, obj):
        return obj.regra.nome
    regra_nome.short_description = 'Régua'

    def status_badge(self, obj):
        cores = {
            'pendente': '#f0ad4e',
            'enviando': '#5bc0de',
            'enviado': '#5cb85c',
            'falha': '#d9534f',
            'cancelado': '#999',
            'bloqueado': '#d9534f',
        }
        cor = cores.get(obj.status, '#999')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            cor, obj.get_status_display(),
        )
    status_badge.short_description = 'Status'

    def has_add_permission(self, request):
        return False


@admin.register(EventoRecebido)
class EventoRecebidoAdmin(admin.ModelAdmin):
    list_display = ['tipo', 'plataforma', 'empresa', 'processado', 'created_at']
    list_filter = ['empresa', 'tipo', 'plataforma', 'processado']
    readonly_fields = [
        'empresa', 'tipo', 'plataforma', 'payload', 'lead', 'cart', 'customer',
        'processado', 'processado_em', 'erro', 'created_at',
    ]
    ordering = ['-created_at']

    def has_add_permission(self, request):
        return False
