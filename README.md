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