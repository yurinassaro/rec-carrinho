# customers/management/commands/check_carts.py

from django.core.management.base import BaseCommand
from customers.models import Cart, Customer
from django.db.models import Count

class Command(BaseCommand):
    help = 'Verifica status dos carrinhos'
    
    def handle(self, *args, **options):
        print("\n📊 ANÁLISE DE CARRINHOS:")
        print("="*50)
        
        # Total de carrinhos
        total = Cart.objects.count()
        print(f"Total de carrinhos: {total}")
        
        # Por status
        by_status = Cart.objects.values('status').annotate(count=Count('id'))
        print("\nPor status:")
        for item in by_status:
            print(f"  - {item['status']}: {item['count']}")
        
        # Últimos 5 carrinhos
        print("\n📦 Últimos 5 carrinhos:")
        for cart in Cart.objects.order_by('-created_at')[:5]:
            print(f"  - {cart.created_at}: {cart.status} (Cliente: {cart.customer.email})")
        
        # Verificar datas
        if Cart.objects.exists():
            oldest = Cart.objects.earliest('created_at')
            newest = Cart.objects.latest('created_at')
            print(f"\n📅 Período dos carrinhos:")
            print(f"  Mais antigo: {oldest.created_at}")
            print(f"  Mais recente: {newest.created_at}")