from customers.models import Cart, Order, Customer
from datetime import datetime, timedelta

print("\n📊 DADOS LOCAIS (JÁ IMPORTADOS):")
print("="*50)
print(f"Clientes: {Customer.objects.count()}")
print(f"Carrinhos: {Cart.objects.count()}")
print(f"Pedidos: {Order.objects.count()}")

# Ver período dos pedidos
if Order.objects.exists():
    oldest = Order.objects.earliest('created_at')
    newest = Order.objects.latest('created_at')
    print(f"\nPeríodo dos pedidos:")
    print(f"  De: {oldest.created_at}")
    print(f"  Até: {newest.created_at}")

# Contar por data
from django.db.models import Count
from django.db.models.functions import TruncDate

pedidos_por_dia = Order.objects.annotate(
    data=TruncDate('created_at')
).values('data').annotate(
    total=Count('id')
).order_by('-data')[:5]

print("\nÚltimos 5 dias com pedidos:")
for p in pedidos_por_dia:
    print(f"  {p['data']}: {p['total']} pedidos")