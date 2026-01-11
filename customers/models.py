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
        Verifica se o lead já é cliente baseado no WhatsApp
        """
        # Buscar por WhatsApp
        customer = Customer.objects.filter(
            phone__contains=self.whatsapp.replace(' ', '').replace('-', '')
        ).first()

        if customer:
            self.is_customer = True
            self.related_customer = customer
            self.status = 'customer'
            return True

        return False