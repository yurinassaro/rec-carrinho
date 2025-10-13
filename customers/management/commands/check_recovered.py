# customers/management/commands/check_recovery.py

from django.core.management.base import BaseCommand
from customers.models import Cart, Order
from datetime import timedelta
from django.utils import timezone

class Command(BaseCommand):
    help = 'Verifica carrinhos que foram recuperados'
    
    def handle(self, *args, **options):
        # Primeiro, garantir que temos pedidos recentes
        print("📊 Verificando carrinhos recuperados...")
        
        # Buscar TODOS os carrinhos com status abandoned
        abandoned_carts = Cart.objects.filter(
            status='abandoned',
            was_recovered=False
        )
        
        print(f"🔍 Analisando {abandoned_carts.count()} carrinhos abandonados...")
        
        recovered_count = 0
        
        for cart in abandoned_carts:
            # Buscar QUALQUER pedido do cliente APÓS o carrinho abandonado
            # Aumentar janela para 30 dias para pegar mais conversões
            orders_after_cart = Order.objects.filter(
                customer=cart.customer,
                created_at__gt=cart.created_at,  # Pedido DEPOIS do carrinho
                created_at__lte=cart.created_at + timedelta(days=30)  # Até 30 dias depois
            ).order_by('created_at')
            
            # Debug - mostrar o que encontrou
            if orders_after_cart.exists():
                print(f"\n📦 Cliente {cart.customer.email}:")
                print(f"   Carrinho abandonado em: {cart.created_at}")
                print(f"   Pedidos encontrados após: {orders_after_cart.count()}")
                
                for order in orders_after_cart[:3]:  # Mostrar até 3 pedidos
                    print(f"   - Pedido #{order.order_number}: {order.created_at} - Status: {order.status}")
            
            # Pegar o primeiro pedido válido
            completed_order = orders_after_cart.filter(
                status__in=['wc-completed', 'wc-processing', 'completed', 'wc-on-hold']
            ).first()
            
            if completed_order:
                # Calcular dias entre abandono e compra
                dias_para_conversao = (completed_order.created_at - cart.created_at).days
                
                # Marcar como recuperado
                cart.was_recovered = True
                cart.recovered_order = completed_order
                cart.recovered_at = completed_order.created_at
                cart.recovery_value = completed_order.total
                cart.status = 'recovered'
                cart.save()
                
                recovered_count += 1
                print(f"✅ RECUPERADO após {dias_para_conversao} dias!")
        
        print(f"\n" + "="*50)
        print(f"📈 RESULTADO:")
        print(f"   - Carrinhos recuperados nesta análise: {recovered_count}")
        
        # Estatísticas totais
        total_recovered = Cart.objects.filter(was_recovered=True).count()
        total_abandoned = Cart.objects.filter(status='abandoned').count()
        
        if total_recovered + total_abandoned > 0:
            taxa = (total_recovered / (total_recovered + total_abandoned)) * 100
            print(f"\n📊 ESTATÍSTICAS TOTAIS:")
            print(f"   - Total recuperados: {total_recovered}")
            print(f"   - Total ainda abandonados: {total_abandoned}")
            print(f"   - Taxa de recuperação: {taxa:.1f}%")
            
            # Valor total recuperado
            from django.db.models import Sum
            valor_total = Cart.objects.filter(
                was_recovered=True
            ).aggregate(Sum('recovery_value'))['recovery_value__sum'] or 0
            
            print(f"   - Valor total recuperado: R$ {valor_total:,.2f}")