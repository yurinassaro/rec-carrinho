from django.db import models
from tenants.models import Empresa


class BlingToken(models.Model):
    """Token OAuth do Bling por empresa"""
    empresa = models.OneToOneField(
        Empresa, on_delete=models.CASCADE, related_name='bling_token'
    )
    access_token = models.TextField()
    refresh_token = models.TextField()
    expires_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'bling_tokens'
        verbose_name = 'Token Bling'
        verbose_name_plural = 'Tokens Bling'

    def __str__(self):
        return f"BlingToken - {self.empresa.nome}"

    @property
    def is_expired(self):
        from django.utils import timezone
        return timezone.now() >= self.expires_at


class BlingPedidoEnviado(models.Model):
    """Log de pedidos já notificados via WhatsApp (evita duplicata)"""
    empresa = models.ForeignKey(
        Empresa, on_delete=models.CASCADE, related_name='bling_pedidos_enviados'
    )
    bling_pedido_id = models.CharField(max_length=100)
    numero_pedido = models.CharField(max_length=100)
    telefone = models.CharField(max_length=20)
    nome_cliente = models.CharField(max_length=200, blank=True)
    status = models.CharField(
        max_length=50, default='em-transito',
        help_text='Status que gerou o envio (processando, embalado, em-transito, concluido, cancelado)'
    )
    enviado_em = models.DateTimeField(auto_now_add=True)
    canal = models.CharField(
        max_length=20, default='meta',
        choices=[('meta', 'Meta Cloud API'), ('wapi', 'W-API')],
        help_text='Canal usado para envio'
    )

    class Meta:
        db_table = 'bling_pedidos_enviados'
        verbose_name = 'Pedido Bling Enviado'
        verbose_name_plural = 'Pedidos Bling Enviados'
        unique_together = ['empresa', 'bling_pedido_id', 'status']
        ordering = ['-enviado_em']

    def __str__(self):
        return f"Pedido #{self.numero_pedido} - {self.empresa.nome}"
