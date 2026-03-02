from django.db import models
from customers.models import Cart, Lead, Customer


class CarrinhoAbandonadoManager(models.Manager):
    """Carrinhos abandonados de clientes que NUNCA compraram"""

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(status='abandoned')
            .filter(customer__completed_orders=0)
            .select_related('customer', 'empresa')
        )


class CarrinhoAbandonado(Cart):
    """Proxy: carrinhos abandonados para remarketing"""

    objects = CarrinhoAbandonadoManager()

    class Meta:
        proxy = True
        verbose_name = 'Carrinho Abandonado'
        verbose_name_plural = 'Carrinhos Abandonados'


class LeadNaoCompradorManager(models.Manager):
    """Leads que NAO sao clientes e NAO converteram"""

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(is_customer=False, converted_to_customer=False)
            .select_related('empresa')
        )


class LeadNaoComprador(Lead):
    """Proxy: leads nao compradores para lookalike/promocoes"""

    objects = LeadNaoCompradorManager()

    class Meta:
        proxy = True
        verbose_name = 'Lead Nao Comprador'
        verbose_name_plural = 'Leads Nao Compradores'


class CompradorManager(models.Manager):
    """Clientes com pelo menos 1 pedido completado"""

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(completed_orders__gt=0)
            .select_related('empresa')
        )


class Comprador(Customer):
    """Proxy: compradores para upsell/base de clientes"""

    objects = CompradorManager()

    class Meta:
        proxy = True
        verbose_name = 'Comprador'
        verbose_name_plural = 'Compradores'
