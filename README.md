Deixe sempre a rota ssh aberta
ssh -N -L 3307:127.0.0.1:3306 -i ~/.ssh/id_ed25519 root@157.245.119.130

# Customer Intelligence - Estrutura do Projeto

## Arquivos Principais
- customer_intelligence/settings.py - Configurações Django
- customers/models.py - Modelos Customer, Cart, Order
- customers/views.py - APIs REST
- customers/admin.py - Interface admin
...

PROBLEMAS NA IMPORACAO PRIMATIA
# 1. Primeiro, debugar os dados para entender o problema
python manage.py debug_cart_data

# 2. Depois, executar a importação corrigida
python manage.py import_customers

# 3. Se ainda houver erros, verificar os logs detalhados
python manage.py import_customers --verbosity=2

EXCLUIR TODA BASE E RECUPERAR NOVAMENTE
# Ou se quiser limpar e reimportar tudo:
python manage.py shell
>>> from customers.models import Customer, Cart, Order
>>> Cart.objects.all().delete()
>>> Order.objects.all().delete()
>>> Customer.objects.all().delete()
>>> exit()
python manage.py import_customers


# como usar
Importação inicial (histórico completo):
bash# Importar 2 anos de dados
python manage.py import_customers --start_date=2023-09-01 --end_date=2025-09-28 --import_type=all
Atualizações diárias:
bash# Importar últimos 7 dias
python manage.py import_customers --start_date=2025-09-22 --end_date=2025-09-28 --import_type=all
Apenas verificar recuperações:
bash# Só rodar análise de recuperação
python manage.py import_customers --import_type=orders --check_recovery