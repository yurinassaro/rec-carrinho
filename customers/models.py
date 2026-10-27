from django.db import models
from django.utils import timezone
from django.db.models import JSONField
import re


class Customer(models.Model):
    """Cliente único com análise inteligente - MULTI-TENANT"""

    CUSTOMER_STATUS = [
        ('never_bought', 'Nunca Comprou'),
        ('first_time', 'Primeira Compra'),
        ('returning', 'Cliente Recorrente'),
        ('abandoned_only', 'Só Abandonou Carrinho'),
        ('inactive', 'Inativo'),
        ('vip', 'VIP'),
    ]

    # Tenant (Empresa)
    empresa = models.ForeignKey(
        'tenants.Empresa',
        on_delete=models.CASCADE,
        related_name='customers',
        null=True,  # Temporario para migracao
        blank=True
    )

    # Identificação
    email = models.EmailField(db_index=True)  # Removido unique=True, sera por empresa
    phone = models.CharField(max_length=20, null=True, blank=True, db_index=True)
    first_name = models.CharField(max_length=100, null=True, blank=True)
    last_name = models.CharField(max_length=100, null=True, blank=True)

    # Endereço de cobrança (billing)
    billing_address = models.CharField(max_length=255, null=True, blank=True, verbose_name='Endereço')
    billing_city = models.CharField(max_length=100, null=True, blank=True, verbose_name='Cidade')
    billing_state = models.CharField(max_length=5, null=True, blank=True, verbose_name='Estado')
    billing_postcode = models.CharField(max_length=20, null=True, blank=True, verbose_name='CEP')

    # Status e classificação
    status = models.CharField(max_length=20, choices=CUSTOMER_STATUS, default='never_bought')
    score = models.IntegerField(default=0)  # 0-100 pontuação do cliente
    
    # Estatísticas de compra
    total_orders = models.IntegerField(default=0)
    completed_orders = models.IntegerField(default=0)
    total_spent = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    average_order_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Estatísticas de carrinho
    total_carts = models.IntegerField(default=0)
    abandoned_carts = models.IntegerField(default=0)
    recovered_carts = models.IntegerField(default=0)
    total_abandoned_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Análise temporal
    first_seen = models.DateTimeField(null=True, blank=True)
    first_purchase = models.DateTimeField(null=True, blank=True)
    last_purchase = models.DateTimeField(null=True, blank=True)
    last_cart_abandoned = models.DateTimeField(null=True, blank=True)
    last_activity = models.DateTimeField(default=timezone.now)
    
    # Comportamento
    days_since_last_purchase = models.IntegerField(null=True, blank=True)
    purchase_frequency_days = models.IntegerField(null=True, blank=True)
    preferred_purchase_hour = models.IntegerField(null=True, blank=True)
    preferred_purchase_weekday = models.IntegerField(null=True, blank=True)
    
    # Análise preditiva
    churn_probability = models.FloatField(default=0)  # 0-1
    purchase_probability = models.FloatField(default=0)  # 0-1
    lifetime_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Metadados
    tags = JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_analyzed = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'customers'
        ordering = ['-score', '-last_activity']
        indexes = [
            models.Index(fields=['empresa', 'status', '-score']),
            models.Index(fields=['empresa', 'email']),
            models.Index(fields=['empresa', 'phone']),
            models.Index(fields=['-last_activity']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['empresa', 'email'],
                name='unique_customer_email_per_empresa'
            )
        ]

    def __str__(self):
        empresa_slug = self.empresa.slug if self.empresa else 'sem-empresa'
        return f"{self.email} ({self.get_status_display()}) - {empresa_slug}"
    
    @property
    def full_name(self):
        return f"{self.first_name or ''} {self.last_name or ''}".strip() or self.email.split('@')[0]
    
    @property
    def whatsapp_number(self):
        """Número formatado para WhatsApp"""
        if not self.phone:
            return None
        
        # Limpar número
        phone = re.sub(r'\D', '', self.phone)
        
        # Validar tamanho
        if len(phone) < 10:
            return None
        
        # Adicionar código do país se necessário
        if not phone.startswith('55'):
            phone = f'55{phone}'
        
        return phone
    
    def calculate_status(self):
        """Calcula o status do cliente baseado no comportamento"""
        if self.completed_orders == 0:
            if self.abandoned_carts > 0:
                return 'abandoned_only'
            return 'never_bought'
        elif self.completed_orders == 1:
            return 'first_time'
        elif self.days_since_last_purchase and self.days_since_last_purchase > 180:
            return 'inactive'
        elif self.total_spent > 1000 or self.completed_orders > 10:
            return 'vip'
        else:
            return 'returning'
    
    def calculate_score(self):
        """Calcula score do cliente (0-100)"""
        score = 0.0  # Usar float desde o início
        
        # Valor gasto (até 40 pontos)
        if self.total_spent > 0:
            score += min(40, float(self.total_spent) / 100)
        
        # Frequência (até 30 pontos)
        if self.completed_orders > 0:
            score += min(30, self.completed_orders * 3)
        
        # Recência (até 20 pontos)
        if self.days_since_last_purchase is not None:
            if self.days_since_last_purchase < 30:
                score += 20
            elif self.days_since_last_purchase < 90:
                score += 10
            elif self.days_since_last_purchase < 180:
                score += 5
        
        # Taxa de conversão (até 10 pontos)
        if self.total_carts > 0:
            conversion_rate = float(self.completed_orders) / float(self.total_carts)
            score += conversion_rate * 10
        
        return min(100, int(score))
    
    def save(self, *args, **kwargs):
        # Atualizar status e score antes de salvar
        self.status = self.calculate_status()
        self.score = self.calculate_score()
        super().save(*args, **kwargs)


class Cart(models.Model):
    """Carrinhos importados do WooCommerce - MULTI-TENANT"""

    CART_STATUS = [
        ('active', 'Ativo'),
        ('abandoned', 'Abandonado'),
        ('recovered', 'Recuperado'),
        ('converted', 'Convertido'),
    ]

    # Tenant (Empresa)
    empresa = models.ForeignKey(
        'tenants.Empresa',
        on_delete=models.CASCADE,
        related_name='carts',
        null=True,  # Temporario para migracao
        blank=True
    )

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='carts')

    # Dados do WooCommerce
    checkout_id = models.CharField(max_length=100, db_index=True)  # Removido unique, sera por empresa
    session_id = models.CharField(max_length=255)
    cart_contents = JSONField()
    cart_total = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Status
    status = models.CharField(max_length=20, choices=CART_STATUS, default='active')
    
    # Análise
    items_count = models.IntegerField(default=0)
    created_at = models.DateTimeField()
    abandoned_at = models.DateTimeField(null=True, blank=True)
    
    # ❌ REMOVER recovered_at DUPLICADO (está repetido abaixo)
    # recovered_at = models.DateTimeField(null=True, blank=True)
    
    # Rastreamento de recuperação (CAMPOS ÚNICOS)
    recovery_email_sent = models.BooleanField(default=False)
    recovery_email_date = models.DateTimeField(null=True, blank=True)
    recovery_whatsapp_sent = models.BooleanField(default=False)
    recovery_whatsapp_date = models.DateTimeField(null=True, blank=True)
    recovery_attempts = models.IntegerField(default=0)
    recovery_coupon = models.CharField(max_length=50, null=True, blank=True)
    
    # ❌ REMOVER coupon_used (já temos recovery_coupon)
    # coupon_used = models.CharField(max_length=50, null=True, blank=True)
    
    # Se foi recuperado
    was_recovered = models.BooleanField(default=False)
    recovered_order = models.ForeignKey('Order', null=True, blank=True,
                                       on_delete=models.SET_NULL,
                                       related_name='recovered_from_cart')
    recovered_at = models.DateTimeField(null=True, blank=True)
    recovery_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    class Meta:
        db_table = 'carts'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['empresa', 'customer', '-created_at']),
            models.Index(fields=['empresa', 'status', '-created_at']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['empresa', 'checkout_id'],
                name='unique_cart_checkout_per_empresa'
            )
        ]


class Order(models.Model):
    """Pedidos importados do WooCommerce - MULTI-TENANT"""

    # Tenant (Empresa)
    empresa = models.ForeignKey(
        'tenants.Empresa',
        on_delete=models.CASCADE,
        related_name='orders',
        null=True,  # Temporario para migracao
        blank=True
    )

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='orders')

    # Dados do pedido
    order_id = models.CharField(max_length=100, db_index=True)  # Removido unique, sera por empresa
    order_number = models.CharField(max_length=100)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=50)
    
    # Datas
    created_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Análise
    items_count = models.IntegerField(default=0)
    payment_method = models.CharField(max_length=100, null=True)
    
    # Relacionamento com carrinho
    related_cart = models.ForeignKey(Cart, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        db_table = 'orders'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['empresa', 'order_id'],
                name='unique_order_id_per_empresa'
            )
        ]


class CustomerAnalysis(models.Model):
    """Análise diária dos clientes"""
    
    date = models.DateField(unique=True)
    
    # Totais
    total_customers = models.IntegerField(default=0)
    new_customers = models.IntegerField(default=0)
    
    # Por status
    never_bought = models.IntegerField(default=0)
    first_time = models.IntegerField(default=0)
    returning = models.IntegerField(default=0)
    abandoned_only = models.IntegerField(default=0)
    inactive = models.IntegerField(default=0)
    vip = models.IntegerField(default=0)
    
    # Carrinhos
    total_carts = models.IntegerField(default=0)
    abandoned_carts = models.IntegerField(default=0)
    recovered_carts = models.IntegerField(default=0)
    
    # Valores
    total_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    abandoned_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Médias
    avg_order_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    conversion_rate = models.FloatField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'customer_analysis'
        ordering = ['-date']


# Adicionar após a classe CustomerAnalysis
# puxa dados do form vibes
class Lead(models.Model):
    """Leads do Form Vibes - MULTI-TENANT"""

    LEAD_STATUS = [
        ('new', 'Novo'),
        ('contacted', 'Contactado'),
        ('customer', 'É Cliente'),
        ('potential', 'Potencial'),
        ('lost', 'Perdido'),
    ]

    # Tenant (Empresa)
    empresa = models.ForeignKey(
        'tenants.Empresa',
        on_delete=models.CASCADE,
        related_name='leads',
        null=True,  # Temporario para migracao
        blank=True
    )

    # Dados do formulário
    form_id = models.CharField(max_length=50, db_index=True)  # Removido unique, sera por empresa
    nome = models.CharField(max_length=200)
    whatsapp = models.CharField(max_length=20, db_index=True)
    numero_sapato = models.CharField(max_length=10, db_index=True)
    ip_address = models.CharField(max_length=45, null=True, blank=True)

    # Status e relacionamentos
    status = models.CharField(max_length=20, choices=LEAD_STATUS, default='new')
    is_customer = models.BooleanField(default=False)
    related_customer = models.ForeignKey(
        Customer,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='leads'
    )

    # Controle de contato
    whatsapp_sent = models.BooleanField(default=False)
    whatsapp_sent_date = models.DateTimeField(null=True, blank=True)
    whatsapp_auto_sent_count = models.IntegerField(default=0)
    whatsapp_auto_status = models.CharField(max_length=50, null=True, blank=True)
    whatsapp_error_message = models.TextField(null=True, blank=True)
    whatsapp_has_conversation = models.BooleanField(null=True, blank=True)
    whatsapp_last_check = models.DateTimeField(null=True, blank=True)
    contact_attempts = models.IntegerField(default=0)
    notes = models.TextField(blank=True)

    # Conversão
    converted_to_customer = models.BooleanField(default=False)
    conversion_date = models.DateTimeField(null=True, blank=True)
    first_order = models.ForeignKey(
        'Order',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='converted_from_lead'
    )

    # Timestamps
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'leads'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['empresa', 'whatsapp', 'numero_sapato']),
            models.Index(fields=['empresa', 'status', '-created_at']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['empresa', 'form_id'],
                name='unique_lead_form_per_empresa'
            )
        ]

    def __str__(self):
        empresa_slug = self.empresa.slug if self.empresa else 'sem-empresa'
        return f"{self.nome} - {self.whatsapp} - {empresa_slug}"

    @property
    def whatsapp_formatted(self):
        """Formata número para WhatsApp"""
        import re
        if not self.whatsapp:
            return None
        phone = re.sub(r'\D', '', self.whatsapp)
        if len(phone) < 10:
            return None
        if not phone.startswith('55'):
            phone = f'55{phone}'
        return phone

    def check_if_customer(self):
        """
        Verifica se o lead já é cliente baseado no WhatsApp.
        Filtra pela mesma empresa do lead.
        Busca pelos ultimos 8 digitos para evitar problemas de formato.
        """
        if not self.whatsapp:
            return False

        # Limpar tudo que nao e digito
        phone_clean = re.sub(r'\D', '', self.whatsapp)
        if len(phone_clean) < 8:
            return False

        # Pegar ultimos 8 digitos (parte significativa sem DDD/pais)
        phone_suffix = phone_clean[-8:]

        # Filtrar pela mesma empresa
        qs = Customer.objects.filter(phone__endswith=phone_suffix)
        if self.empresa_id:
            qs = qs.filter(empresa=self.empresa)

        customer = qs.first()

        if customer:
            self.is_customer = True
            self.related_customer = customer
            self.status = 'customer'
            return True

        # Tentar tambem pelo email se tiver nome completo
        # (leads com mesmo nome podem ser o mesmo cliente)
        return False


class MensagemWhatsApp(models.Model):
    """Historico centralizado de todas as mensagens WhatsApp enviadas."""

    TIPO_CHOICES = [
        ('lead', 'Lead Novo (nao cliente)'),
        ('lead_cliente', 'Lead Ja Cliente'),
        ('cart', 'Carrinho Abandonado'),
        ('cliente_inativo', 'Cliente Inativo (reativacao)'),
        ('pedido_novo', 'Pedido Novo'),
        ('pedido_processando', 'Pedido Processando'),
        ('pedido_embalado', 'Pedido Embalado'),
        ('pedido_transito', 'Pedido em Transito'),
        ('pedido_concluido', 'Pedido Concluido'),
        ('pedido_cancelado', 'Pedido Cancelado'),
        ('resposta_cliente', 'Resposta do Cliente'),
        ('auto_resposta', 'Auto-resposta do Bot'),
        ('atendimento_humano', 'Atendimento Humano (Inbox)'),
    ]

    CANAL_CHOICES = [
        ('meta', 'Meta Cloud API'),
        ('wapi', 'W-API'),
    ]

    STATUS_CHOICES = [
        ('enviado', 'Enviado'),
        ('falha', 'Falha'),
        ('entregue', 'Entregue'),
        ('lido', 'Lido'),
    ]

    empresa = models.ForeignKey(
        'tenants.Empresa',
        on_delete=models.CASCADE,
        related_name='mensagens_whatsapp',
    )
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES)
    canal = models.CharField(max_length=10, choices=CANAL_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='enviado')

    # Destinatario
    destinatario_nome = models.CharField(max_length=200)
    destinatario_telefone = models.CharField(max_length=20)

    # Conteudo
    template_name = models.CharField(
        max_length=100, blank=True,
        help_text='Nome do template Meta (se canal=meta)'
    )
    template_params = models.JSONField(
        default=list, blank=True,
        help_text='Parametros do template Meta'
    )
    mensagem_texto = models.TextField(
        blank=True,
        help_text='Texto da mensagem (se canal=wapi)'
    )

    # Resultado
    error_message = models.TextField(blank=True)
    api_response = models.JSONField(default=dict, blank=True)
    midia_arquivo = models.FileField(
        upload_to='inbox_midia/%Y/%m/', blank=True, null=True,
        help_text='Cópia local da mídia enviada pelo inbox (áudio/imagem) para replay',
    )

    # ID da mensagem no Meta (para rastrear status via webhook)
    meta_message_id = models.CharField(
        max_length=200, blank=True, db_index=True,
        help_text='wamid retornado pela Meta API'
    )

    # Tracking de interacao (atualizado via webhook Meta)
    entregue_em = models.DateTimeField(null=True, blank=True)
    lido_em = models.DateTimeField(null=True, blank=True)
    respondido = models.BooleanField(default=False)
    respondido_em = models.DateTimeField(null=True, blank=True)
    resposta_texto = models.TextField(blank=True)
    clicou_link = models.BooleanField(default=False)
    clicou_link_em = models.DateTimeField(null=True, blank=True)
    encaminhado_humano = models.BooleanField(default=False)
    encaminhado_humano_em = models.DateTimeField(null=True, blank=True)

    # Relacionamentos opcionais
    lead = models.ForeignKey(
        Lead, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='mensagens_whatsapp',
    )
    cart = models.ForeignKey(
        Cart, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='mensagens_whatsapp',
    )
    customer = models.ForeignKey(
        Customer, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='mensagens_whatsapp',
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'mensagens_whatsapp'
        verbose_name = 'Mensagem WhatsApp'
        verbose_name_plural = 'Mensagens WhatsApp'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['empresa', 'tipo', '-created_at']),
            models.Index(fields=['empresa', 'canal', '-created_at']),
            models.Index(fields=['destinatario_telefone', '-created_at']),
            models.Index(fields=['meta_message_id']),
        ]


class LeadAtacado(models.Model):
    """Leads de atacado recebidos do formulário posvendafacil.com.br"""

    STATUS_EMPRESA_CHOICES = [
        ('tenho_empresa_vendo_calcados', 'Tenho empresa - vendo calçados'),
        ('tenho_empresa_nao_vendo_sapatos', 'Tenho empresa - não vendo sapatos'),
        ('nao_tenho_empresa_vendo_sapatos', 'Não tenho empresa - vendo sapatos'),
        ('nao_tenho_empresa_nao_vendo_sapatos', 'Não tenho empresa - não vendo sapatos'),
    ]

    PLANO_CHOICES = [
        ('sortidos', 'Sortidos (Acima de 36 pares)'),
        ('grade', 'Grade (Acima de 12 por grade)'),
    ]

    PRIVATE_LABEL_CHOICES = [
        ('sim', 'Sim'),
        ('nao', 'Não'),
        ('talvez', 'Talvez no futuro'),
    ]

    LEAD_STATUS = [
        ('novo', 'Novo'),
        ('conversando', 'Conversando'),
        ('potencial', 'Potencial'),
        ('nao_potencial', 'Não Potencial'),
        ('passado_vendedor', 'Passado p/ Vendedor'),
        ('curioso', 'Curioso'),
        ('convertido', 'Virou Cliente'),
        ('perdido', 'Perdido'),
    ]

    PRIORIDADE_CHOICES = [
        ('baixa', 'Baixa'),
        ('media', 'Média'),
        ('alta', 'Alta'),
        ('urgente', 'Urgente'),
    ]

    # Tenant
    empresa = models.ForeignKey(
        'tenants.Empresa',
        on_delete=models.CASCADE,
        related_name='leads_atacado',
    )

    # Dados pessoais
    nome_completo = models.CharField(max_length=255)
    cpf = models.CharField(max_length=14)
    email = models.EmailField()
    whatsapp = models.CharField(max_length=20, db_index=True)
    cidade = models.CharField(max_length=100)
    estado = models.CharField(max_length=2)

    # Perfil do lead
    status_empresa = models.CharField(max_length=50, choices=STATUS_EMPRESA_CHOICES)

    # Dados empresa (opções 1 e 2)
    nome_empresa = models.CharField(max_length=255, blank=True, default='')
    cnpj = models.CharField(max_length=18, blank=True, default='')
    nicho_empresarial = models.CharField(max_length=255, blank=True, default='')
    instagram = models.CharField(max_length=255, blank=True, default='')
    site_vendas = models.CharField(max_length=255, blank=True, default='')

    # Canais de vendas (opção 3)
    canais_vendas = models.CharField(max_length=500, blank=True, default='')

    # Sobre voce (opção 4)
    sobre_voce = models.TextField(blank=True, default='')

    # Plano e private label
    plano_interesse = models.CharField(max_length=20, choices=PLANO_CHOICES, blank=True, default='')
    private_label = models.CharField(max_length=20, choices=PRIVATE_LABEL_CHOICES, blank=True, default='')

    # CRM
    status = models.CharField(max_length=20, choices=LEAD_STATUS, default='novo')
    prioridade = models.CharField(max_length=10, choices=PRIORIDADE_CHOICES, default='media')
    responsavel = models.CharField(max_length=100, blank=True, default='', help_text='Nome do vendedor responsável')
    notas = models.TextField(blank=True, default='')
    proximo_contato = models.DateTimeField(null=True, blank=True, help_text='Data do próximo follow-up')
    valor_estimado = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text='Valor estimado do pedido')

    # Controle WhatsApp
    whatsapp_enviado = models.BooleanField(default=False)
    whatsapp_enviado_em = models.DateTimeField(null=True, blank=True)
    whatsapp_tentativas = models.IntegerField(default=0)
    whatsapp_status = models.CharField(max_length=50, blank=True, default='')
    whatsapp_erro = models.TextField(blank=True, default='')

    # Metadados
    origem = models.CharField(max_length=50, default='formulario', help_text='formulario, api, manual, importacao')
    ip_cliente = models.GenericIPAddressField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'leads_atacado'
        verbose_name = 'Lead Atacado'
        verbose_name_plural = 'Leads Atacado'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['empresa', 'status', '-created_at']),
            models.Index(fields=['empresa', 'status_empresa', '-created_at']),
            models.Index(fields=['whatsapp']),
        ]

    def __str__(self):
        return f'{self.nome_completo} - {self.get_status_empresa_display()}'

    @property
    def whatsapp_formatted(self):
        """Formata WhatsApp para envio (55 + DDD + numero)"""
        numero = ''.join(filter(str.isdigit, self.whatsapp))
        if len(numero) in (10, 11):
            return '55' + numero
        if len(numero) == 13 and numero.startswith('55'):
            return numero
        return numero

    @property
    def primeiro_nome(self):
        return self.nome_completo.split()[0] if self.nome_completo else 'Cliente'


class Pipeline(models.Model):
    """Pipeline/funil de vendas genérico (Atacado, Troca, Varejo, etc.)"""

    empresa = models.ForeignKey(
        'tenants.Empresa',
        on_delete=models.CASCADE,
        related_name='pipelines',
    )
    nome = models.CharField(max_length=100, help_text='Ex: Atacado, Troca, Varejo')
    slug = models.SlugField(max_length=100)
    ativo = models.BooleanField(default=True)
    ordem = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'pipelines'
        verbose_name = 'Pipeline'
        verbose_name_plural = 'Pipelines'
        ordering = ['ordem', 'nome']
        unique_together = ['empresa', 'slug']

    def __str__(self):
        return f'{self.nome} ({self.empresa.nome})'

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            self.slug = slugify(self.nome)
        super().save(*args, **kwargs)


class PipelineEtapa(models.Model):
    """Etapa/estágio dentro de um pipeline"""

    pipeline = models.ForeignKey(
        Pipeline,
        on_delete=models.CASCADE,
        related_name='etapas',
    )
    nome = models.CharField(max_length=100, help_text='Ex: Novo, Conversando, Fechado')
    slug = models.SlugField(max_length=100)
    cor = models.CharField(max_length=7, default='#2196F3', help_text='Cor hex para o Kanban')
    ordem = models.IntegerField(default=0)
    is_final = models.BooleanField(default=False, help_text='Etapa final (convertido/perdido)')

    class Meta:
        db_table = 'pipeline_etapas'
        verbose_name = 'Etapa do Pipeline'
        verbose_name_plural = 'Etapas do Pipeline'
        ordering = ['ordem']
        unique_together = ['pipeline', 'slug']

    def __str__(self):
        return f'{self.nome} ({self.pipeline.nome})'

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            self.slug = slugify(self.nome)
        super().save(*args, **kwargs)


class ContatoPipeline(models.Model):
    """Contato dentro de um pipeline - capturado via extensão Chrome ou manual"""

    PRIORIDADE_CHOICES = [
        ('baixa', 'Baixa'),
        ('media', 'Média'),
        ('alta', 'Alta'),
        ('urgente', 'Urgente'),
    ]

    empresa = models.ForeignKey(
        'tenants.Empresa',
        on_delete=models.CASCADE,
        related_name='contatos_pipeline',
    )
    pipeline = models.ForeignKey(
        Pipeline,
        on_delete=models.CASCADE,
        related_name='contatos',
    )
    etapa = models.ForeignKey(
        PipelineEtapa,
        on_delete=models.SET_NULL,
        null=True,
        related_name='contatos',
    )

    # Dados do contato
    nome = models.CharField(max_length=255)
    telefone = models.CharField(max_length=20, blank=True, default='', db_index=True)
    instagram = models.CharField(max_length=100, blank=True, default='', db_index=True, help_text='Username do Instagram (sem @)')
    email = models.EmailField(blank=True, default='')
    empresa_contato = models.CharField(max_length=255, blank=True, default='', verbose_name='Empresa do contato')

    # CRM
    prioridade = models.CharField(max_length=10, choices=PRIORIDADE_CHOICES, default='media')
    responsavel = models.CharField(max_length=100, blank=True, default='')
    notas = models.TextField(blank=True, default='')
    valor_estimado = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    proximo_contato = models.DateTimeField(null=True, blank=True)

    # Relacionamento com Customer/Lead existente
    customer = models.ForeignKey(
        Customer, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='contatos_pipeline',
    )

    # Metadados
    origem = models.CharField(max_length=50, default='chrome_extension')
    tags = JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'contatos_pipeline'
        verbose_name = 'Contato no Pipeline'
        verbose_name_plural = 'Contatos no Pipeline'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['empresa', 'pipeline', 'etapa', '-created_at']),
            models.Index(fields=['telefone']),
            models.Index(fields=['empresa', 'instagram']),
        ]

    def __str__(self):
        return f'{self.nome} - {self.pipeline.nome} / {self.etapa.nome if self.etapa else "Sem etapa"}'


class InstagramDMTemplate(models.Model):
    """
    Mensagens de DM do Instagram (boas-vindas a novos seguidores).
    A extensao sorteia uma ativa e insere no campo do Instagram, trocando
    {nome} pelo primeiro nome do cliente. Rotacionar varias evita bloqueio.
    """
    empresa = models.ForeignKey(
        'tenants.Empresa',
        on_delete=models.CASCADE,
        related_name='instagram_dm_templates',
    )
    texto = models.TextField(help_text='Use {nome} para inserir o primeiro nome do cliente.')
    ativo = models.BooleanField(default=True)
    ordem = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'instagram_dm_templates'
        verbose_name = 'Template de DM Instagram'
        verbose_name_plural = 'Templates de DM Instagram'
        ordering = ['ordem', 'id']

    def __str__(self):
        return f'{self.empresa.nome}: {self.texto[:40]}'