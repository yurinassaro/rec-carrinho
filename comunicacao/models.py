"""
Motor de Réguas de Comunicação Inteligente.

Permite configurar regras automatizadas de envio por empresa,
com frequency capping, multi-step campaigns, e engagement tracking.
"""
from django.db import models


class RegraComunicacao(models.Model):
    """
    Régua de comunicação configurável por empresa.
    Define QUANDO, PARA QUEM, e O QUE enviar.
    """

    GATILHO_CHOICES = [
        # Eventos de carrinho
        ('cart_abandoned', 'Carrinho Abandonado'),
        ('cart_high_value', 'Carrinho Alto Valor (> R$X)'),
        # Eventos de lead
        ('lead_new', 'Lead Novo (form preenchido)'),
        ('lead_repeat_form', 'Lead Preencheu Form Novamente'),
        # Eventos de cliente
        ('customer_inactive_30', 'Cliente Inativo 30 dias'),
        ('customer_inactive_60', 'Cliente Inativo 60 dias'),
        ('customer_inactive_90', 'Cliente Inativo 90+ dias'),
        ('customer_first_purchase', 'Primeira Compra (pós-venda)'),
        ('customer_repeat_purchase', 'Compra Recorrente'),
        ('customer_vip', 'Cliente VIP'),
        # Eventos de pedido (transacional)
        ('order_created', 'Pedido Criado'),
        ('order_processing', 'Pedido Processando'),
        ('order_shipped', 'Pedido Embalado'),
        ('order_in_transit', 'Pedido em Trânsito'),
        ('order_delivered', 'Pedido Entregue'),
        ('order_cancelled', 'Pedido Cancelado'),
        # Manual
        ('manual', 'Disparo Manual'),
    ]

    CANAL_CHOICES = [
        ('meta', 'Meta Cloud API'),
        ('wapi', 'W-API'),
        ('auto', 'Automático (Meta → W-API fallback)'),
    ]

    empresa = models.ForeignKey(
        'tenants.Empresa',
        on_delete=models.CASCADE,
        related_name='regras_comunicacao',
    )

    # Identificação
    nome = models.CharField(
        max_length=200,
        help_text='Ex: Carrinho abandonado - etapa 1'
    )
    descricao = models.TextField(blank=True)
    gatilho = models.CharField(max_length=30, choices=GATILHO_CHOICES)
    ativo = models.BooleanField(default=True)
    prioridade = models.IntegerField(
        default=10,
        help_text='Menor = mais prioritário. Quando duas réguas se aplicam ao mesmo contato, a de menor número ganha.'
    )

    # Multi-step: etapa da sequência (1, 2, 3...)
    etapa = models.IntegerField(
        default=1,
        help_text='Etapa na sequência. Etapa 2 só dispara se etapa 1 foi enviada e não houve conversão.'
    )

    # Timing
    delay_horas = models.IntegerField(
        default=0,
        help_text='Horas após o gatilho para enviar. Ex: 2 = envia 2h depois do carrinho abandonado.'
    )
    horario_inicio = models.TimeField(
        default='09:00',
        help_text='Não enviar antes deste horário'
    )
    horario_fim = models.TimeField(
        default='20:00',
        help_text='Não enviar depois deste horário'
    )
    dias_semana = models.JSONField(
        default=list,
        blank=True,
        help_text='Dias permitidos [0=seg...6=dom]. Vazio = todos.'
    )

    # Condições extras (filtros JSON)
    condicoes = models.JSONField(
        default=dict,
        blank=True,
        help_text='Filtros JSON. Ex: {"min_cart_value": 50, "min_orders": 1, "max_engagement_score": 80}'
    )

    # Frequency capping
    cooldown_horas = models.IntegerField(
        default=168,
        help_text='Horas mínimas entre envios da MESMA régua para o MESMO telefone. 168 = 7 dias.'
    )
    max_msgs_semana_telefone = models.IntegerField(
        default=3,
        help_text='Máximo de mensagens por semana para o MESMO telefone (todas as réguas somadas).'
    )
    max_envios_total = models.IntegerField(
        default=0,
        help_text='Máximo de vezes que esta régua envia para o mesmo contato. 0 = sem limite.'
    )
    max_envios_dia = models.IntegerField(
        default=50,
        help_text='Máximo de envios desta régua por dia (anti-spam global).'
    )

    # Blacklist automática
    max_ignorados_consecutivos = models.IntegerField(
        default=3,
        help_text='Se o contato ignorou N msgs consecutivas (não leu), parar de enviar. 0 = desativado.'
    )

    # Canal e template
    canal = models.CharField(max_length=5, choices=CANAL_CHOICES, default='meta')
    template_meta = models.CharField(
        max_length=100, blank=True,
        help_text='Nome do template aprovado no Meta Business'
    )
    template_params_map = models.JSONField(
        default=list,
        blank=True,
        help_text='Parâmetros do template. Ex: ["nome", "cupom", "desconto", "validade"]'
    )
    texto_wapi = models.TextField(
        blank=True,
        help_text='Texto para W-API. Variáveis: {nome}, {numero}, {valor}, {cupom}, {desconto}, {validade}'
    )
    button_url_param = models.CharField(
        max_length=50, blank=True,
        help_text='Campo do objeto para URL dinâmica do botão Meta. Ex: session_id'
    )

    # Instância W-API específica
    instancia_wapi = models.ForeignKey(
        'tenants.InstanciaWAPI',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        help_text='Instância W-API específica. Vazio = usa fallback da empresa.'
    )

    # Cupom (sobrescreve o padrão da empresa se preenchido)
    usar_cupom = models.BooleanField(default=False)
    cupom_codigo = models.CharField(max_length=50, blank=True)
    cupom_desconto = models.CharField(max_length=10, blank=True)
    cupom_validade = models.CharField(max_length=50, blank=True)

    # Estatísticas (atualizadas automaticamente)
    total_enviados = models.IntegerField(default=0)
    total_entregues = models.IntegerField(default=0)
    total_lidos = models.IntegerField(default=0)
    total_respondidos = models.IntegerField(default=0)
    total_convertidos = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'regras_comunicacao'
        verbose_name = 'Régua de Comunicação'
        verbose_name_plural = 'Réguas de Comunicação'
        ordering = ['empresa', 'gatilho', 'etapa', 'prioridade']
        indexes = [
            models.Index(fields=['empresa', 'gatilho', 'ativo']),
            models.Index(fields=['empresa', 'ativo', 'prioridade']),
        ]

    def __str__(self):
        return f"{self.nome} (etapa {self.etapa}) - {self.empresa.slug}"

    def get_cupom_params(self):
        """Retorna parâmetros de cupom (da régra ou fallback da empresa)."""
        if self.usar_cupom:
            return {
                'cupom': self.cupom_codigo or self.empresa.meta_cupom_codigo,
                'desconto': self.cupom_desconto or self.empresa.meta_cupom_desconto,
                'validade': self.cupom_validade or self.empresa.meta_cupom_validade,
            }
        return {}


class ContatoBlacklist(models.Model):
    """
    Telefones que não devem receber mensagens.
    Preenchido automaticamente (spam report, bloqueio) ou manualmente.
    """
    MOTIVO_CHOICES = [
        ('opt_out', 'Opt-out (pediu para parar)'),
        ('spam_report', 'Reportou spam'),
        ('blocked', 'Bloqueou o número'),
        ('invalid_number', 'Número inválido'),
        ('too_many_ignored', 'Ignorou muitas mensagens'),
        ('manual', 'Bloqueio manual'),
    ]

    empresa = models.ForeignKey(
        'tenants.Empresa',
        on_delete=models.CASCADE,
        related_name='blacklist',
    )
    telefone = models.CharField(max_length=20, db_index=True)
    motivo = models.CharField(max_length=20, choices=MOTIVO_CHOICES)
    detalhes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'contato_blacklist'
        verbose_name = 'Contato Bloqueado'
        verbose_name_plural = 'Contatos Bloqueados'
        constraints = [
            models.UniqueConstraint(
                fields=['empresa', 'telefone'],
                name='unique_blacklist_per_empresa'
            )
        ]

    def __str__(self):
        return f"{self.telefone} - {self.get_motivo_display()}"


class FilaEnvio(models.Model):
    """
    Fila de mensagens agendadas para envio.
    O motor de réguas avalia as condições e enfileira aqui.
    O worker Celery consome a fila e envia.
    """
    STATUS_CHOICES = [
        ('pendente', 'Pendente'),
        ('enviando', 'Enviando'),
        ('enviado', 'Enviado'),
        ('falha', 'Falha'),
        ('cancelado', 'Cancelado'),
        ('bloqueado', 'Bloqueado (blacklist/capping)'),
    ]

    empresa = models.ForeignKey(
        'tenants.Empresa',
        on_delete=models.CASCADE,
        related_name='fila_envios',
    )
    regra = models.ForeignKey(
        RegraComunicacao,
        on_delete=models.CASCADE,
        related_name='fila_envios',
    )

    # Destinatário
    telefone = models.CharField(max_length=20)
    nome = models.CharField(max_length=200)

    # Referências ao objeto que gerou o envio
    lead = models.ForeignKey(
        'customers.Lead', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='fila_envios',
    )
    cart = models.ForeignKey(
        'customers.Cart', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='fila_envios',
    )
    customer = models.ForeignKey(
        'customers.Customer', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='fila_envios',
    )

    # Agendamento
    agendar_para = models.DateTimeField(
        help_text='Quando enviar (respeita horário comercial da régra).'
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pendente')

    # Resultado (preenchido após envio)
    mensagem = models.ForeignKey(
        'customers.MensagemWhatsApp', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='fila_envio',
    )
    erro = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    processado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'fila_envio'
        verbose_name = 'Item na Fila'
        verbose_name_plural = 'Fila de Envio'
        ordering = ['agendar_para']
        indexes = [
            models.Index(fields=['status', 'agendar_para']),
            models.Index(fields=['empresa', 'telefone', '-created_at']),
            models.Index(fields=['empresa', 'regra', 'status']),
        ]

    def __str__(self):
        return f"{self.telefone} - {self.regra.nome} - {self.status}"


class EventoRecebido(models.Model):
    """
    Log de eventos recebidos de qualquer plataforma.
    API genérica: POST /api/v1/events/
    """
    TIPO_CHOICES = [
        ('cart.abandoned', 'Carrinho Abandonado'),
        ('cart.recovered', 'Carrinho Recuperado'),
        ('order.created', 'Pedido Criado'),
        ('order.status_changed', 'Status do Pedido Mudou'),
        ('lead.created', 'Lead Criado'),
        ('customer.created', 'Cliente Criado'),
        ('customer.updated', 'Cliente Atualizado'),
    ]

    PLATAFORMA_CHOICES = [
        ('woocommerce', 'WooCommerce'),
        ('shopify', 'Shopify'),
        ('nuvemshop', 'Nuvemshop'),
        ('api', 'API Genérica'),
        ('webhook', 'Webhook'),
        ('manual', 'Manual'),
    ]

    empresa = models.ForeignKey(
        'tenants.Empresa',
        on_delete=models.CASCADE,
        related_name='eventos',
    )
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES)
    plataforma = models.CharField(max_length=20, choices=PLATAFORMA_CHOICES, default='api')

    # Dados do evento
    payload = models.JSONField(default=dict)

    # Referências (preenchidas após processamento)
    lead = models.ForeignKey(
        'customers.Lead', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='eventos',
    )
    cart = models.ForeignKey(
        'customers.Cart', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='eventos',
    )
    customer = models.ForeignKey(
        'customers.Customer', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='eventos',
    )

    # Processamento
    processado = models.BooleanField(default=False)
    processado_em = models.DateTimeField(null=True, blank=True)
    erro = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'eventos_recebidos'
        verbose_name = 'Evento Recebido'
        verbose_name_plural = 'Eventos Recebidos'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['empresa', 'tipo', '-created_at']),
            models.Index(fields=['processado', '-created_at']),
        ]

    def __str__(self):
        return f"{self.tipo} ({self.plataforma}) - {self.empresa.slug}"
