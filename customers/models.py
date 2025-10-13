from django.db import models
from django.utils import timezone
from django.db.models import JSONField
import re

class Customer(models.Model):
    """Cliente único com análise inteligente"""
    
    CUSTOMER_STATUS = [
        ('never_bought', 'Nunca Comprou'),
        ('first_time', 'Primeira Compra'),
        ('returning', 'Cliente Recorrente'),
        ('abandoned_only', 'Só Abandonou Carrinho'),
        ('inactive', 'Inativo'),
        ('vip', 'VIP'),
    ]
    
    # Identificação
    email = models.EmailField(unique=True, db_index=True)
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
            models.Index(fields=['status', '-score']),
            models.Index(fields=['email', 'phone']),
            models.Index(fields=['-last_activity']),
        ]
    
    def __str__(self):
        return f"{self.email} ({self.get_status_display()})"
    
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
    """Carrinhos importados do WooCommerce"""
    
    CART_STATUS = [
        ('active', 'Ativo'),
        ('abandoned', 'Abandonado'),
        ('recovered', 'Recuperado'),
        ('converted', 'Convertido'),
    ]
    
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='carts')
    
    # Dados do WooCommerce
    checkout_id = models.CharField(max_length=100, unique=True)
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
            models.Index(fields=['customer', '-created_at']),
            models.Index(fields=['status', '-created_at']),
        ]


class Order(models.Model):
    """Pedidos importados do WooCommerce"""
    
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='orders')
    
    # Dados do pedido
    order_id = models.CharField(max_length=100, unique=True)
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