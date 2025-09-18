# customers/management/commands/import_customers.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, timedelta
from sshtunnel import SSHTunnelForwarder
import pymysql
from customers.models import Customer, Cart, Order
import json
import os
from dotenv import load_dotenv

load_dotenv()

class Command(BaseCommand):
    help = 'Importa e analisa clientes do WooCommerce'
    
    def __init__(self):
        super().__init__()
        self.ssh_config = {
            'host': os.getenv('SSH_HOST'),
            'user': os.getenv('SSH_USER'),
            'key': os.getenv('SSH_KEY'),
        }
        
        self.db_config = {
            'user': os.getenv('WOO_DB_USER'),
            'password': os.getenv('WOO_DB_PASS'),
            'database': os.getenv('WOO_DB_NAME'),
        }
    
    def handle(self, *args, **options):
        self.stdout.write('🚀 Iniciando importação inteligente de clientes...')
        
        with SSHTunnelForwarder(
            (self.ssh_config['host'], 22),
            ssh_username=self.ssh_config['user'],
            ssh_pkey=self.ssh_config['key'],
            remote_bind_address=("127.0.0.1", 3306),
            local_bind_address=("127.0.0.1", 0),
        ) as tunnel:
            
            self.stdout.write(f'✅ Túnel SSH conectado')
            
            conn = pymysql.connect(
                host="127.0.0.1",
                port=tunnel.local_bind_port,
                user=self.db_config['user'],
                password=self.db_config['password'],
                database=self.db_config['database'],
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
            )
            
            with conn.cursor() as cursor:
                # 1. Importar clientes e carrinhos
                self.import_abandoned_carts(cursor)
                
                # 2. Importar pedidos
                self.import_orders(cursor)
                
                # 3. Análise inteligente
                self.analyze_customers()
                
            conn.close()
    
    def import_abandoned_carts(self, cursor):
        """Importa carrinhos abandonados e cria/atualiza clientes"""
        
        query = """
        SELECT 
            id,
            checkout_id,
            email,
            cart_contents,
            cart_total,
            session_id,
            other_fields,
            order_status,
            time
        FROM cli_cartflows_ca_cart_abandonment
        WHERE time >= DATE_SUB(NOW(), INTERVAL 90 DAY)
        ORDER BY time DESC
        """
        
        cursor.execute(query)
        carts = cursor.fetchall()
        
        self.stdout.write(f'📦 Processando {len(carts)} carrinhos...')
        
        for cart_data in carts:
            # Criar ou atualizar cliente
            customer_data = {
                'email': cart_data['email']
            }
            
            # Extrair dados do other_fields
            if cart_data['other_fields']:
                try:
                    other = json.loads(cart_data['other_fields'])
                    customer_data['phone'] = other.get('phone', '')
                    customer_data['first_name'] = other.get('first_name', '')
                    customer_data['last_name'] = other.get('last_name', '')
                except:
                    pass
            
            customer, created = Customer.objects.update_or_create(
                email=cart_data['email'],
                defaults=customer_data
            )
            
            # Criar carrinho
            Cart.objects.update_or_create(
                checkout_id=cart_data['checkout_id'],
                defaults={
                    'customer': customer,
                    'session_id': cart_data['session_id'],
                    'cart_contents': json.loads(cart_data['cart_contents']) if isinstance(cart_data['cart_contents'], str) else cart_data['cart_contents'],
                    'cart_total': float(cart_data['cart_total']),
                    'status': 'abandoned' if cart_data['order_status'] == 'abandoned' else 'active',
                    'created_at': cart_data['time'],
                }
            )
            
            # Atualizar estatísticas do cliente
            customer.total_carts = customer.carts.count()
            customer.abandoned_carts = customer.carts.filter(status='abandoned').count()
            customer.total_abandoned_value = customer.carts.filter(
                status='abandoned'
            ).aggregate(Sum('cart_total'))['cart_total__sum'] or 0
            
            if not customer.first_seen or cart_data['time'] < customer.first_seen:
                customer.first_seen = cart_data['time']
            
            customer.save()
    
    def import_orders(self, cursor):
        """Importa pedidos e vincula com carrinhos"""
        
        # Descobrir prefixo das tabelas
        cursor.execute("SHOW TABLES LIKE '%posts'")
        tables = cursor.fetchall()
        
        if not tables:
            self.stdout.write('❌ Tabelas WordPress não encontradas')
            return
        
        posts_table = list(tables[0].values())[0]
        prefix = posts_table.replace('posts', '')
        
        query = f"""
        SELECT 
            p.ID as order_id,
            p.post_date as created_at,
            p.post_status as status,
            pm_email.meta_value as email,
            pm_phone.meta_value as phone,
            pm_fname.meta_value as first_name,
            pm_lname.meta_value as last_name,
            pm_total.meta_value as total
        FROM {posts_table} p
        LEFT JOIN {prefix}postmeta pm_email ON p.ID = pm_email.post_id 
            AND pm_email.meta_key = '_billing_email'
        LEFT JOIN {prefix}postmeta pm_phone ON p.ID = pm_phone.post_id 
            AND pm_phone.meta_key = '_billing_phone'
        LEFT JOIN {prefix}postmeta pm_fname ON p.ID = pm_fname.post_id 
            AND pm_fname.meta_key = '_billing_first_name'
        LEFT JOIN {prefix}postmeta pm_lname ON p.ID = pm_lname.post_id 
            AND pm_lname.meta_key = '_billing_last_name'
        LEFT JOIN {prefix}postmeta pm_total ON p.ID = pm_total.post_id 
            AND pm_total.meta_key = '_order_total'
        WHERE p.post_type = 'shop_order'
        AND p.post_status IN ('wc-completed', 'wc-processing', 'wc-on-hold')
        AND p.post_date >= DATE_SUB(NOW(), INTERVAL 365 DAY)
        """
        
        cursor.execute(query)
        orders = cursor.fetchall()
        
        self.stdout.write(f'🛍️ Processando {len(orders)} pedidos...')
        
        for order_data in orders:
            if not order_data['email']:
                continue
            
            # Criar ou atualizar cliente
            customer, created = Customer.objects.update_or_create(
                email=order_data['email'],
                defaults={
                    'phone': order_data['phone'] or '',
                    'first_name': order_data['first_name'] or '',
                    'last_name': order_data['last_name'] or '',
                }
            )
            
            # Criar pedido
            Order.objects.update_or_create(
                order_id=str(order_data['order_id']),
                defaults={
                    'customer': customer,
                    'order_number': str(order_data['order_id']),
                    'total': float(order_data['total'] or 0),
                    'status': order_data['status'],
                    'created_at': order_data['created_at'],
                }
            )
    
    def analyze_customers(self):
        """Análise inteligente de clientes"""
        
        self.stdout.write('🧠 Executando análise inteligente...')
        
        for customer in Customer.objects.all():
            # Atualizar estatísticas de pedidos
            orders = customer.orders.filter(status__in=['wc-completed', 'wc-processing'])
            customer.total_orders = customer.orders.count()
            customer.completed_orders = orders.count()
            customer.total_spent = orders.aggregate(Sum('total'))['total__sum'] or 0
            
            if customer.completed_orders > 0:
                customer.average_order_value = customer.total_spent / customer.completed_orders
                customer.first_purchase = orders.order_by('created_at').first().created_at
                customer.last_purchase = orders.order_by('-created_at').first().created_at
                customer.days_since_last_purchase = (timezone.now() - customer.last_purchase).days
            
            # Verificar carrinhos que viraram pedidos
            for cart in customer.carts.filter(status='abandoned'):
                # Verificar se houve pedido após o carrinho
                order_after_cart = customer.orders.filter(
                    created_at__gte=cart.created_at,
                    created_at__lte=cart.created_at + timedelta(days=7)
                ).first()
                
                if order_after_cart:
                    cart.status = 'recovered'
                    cart.recovered_at = order_after_cart.created_at
                    cart.related_order = order_after_cart
                    cart.save()
                    
                    customer.recovered_carts += 1
            
            # Calcular última atividade
            last_activities = []
            if customer.last_purchase:
                last_activities.append(customer.last_purchase)
            if customer.carts.exists():
                last_activities.append(customer.carts.latest('created_at').created_at)
            
            if last_activities:
                customer.last_activity = max(last_activities)
            
            # Salvar (isso também recalcula status e score)
            customer.save()
        
        self.stdout.write(self.style.SUCCESS('✅ Importação e análise concluídas!'))
        
        # Estatísticas finais
        stats = {
            'total': Customer.objects.count(),
            'never_bought': Customer.objects.filter(status='never_bought').count(),
            'abandoned_only': Customer.objects.filter(status='abandoned_only').count(),
            'active': Customer.objects.filter(status__in=['first_time', 'returning', 'vip']).count(),
        }
        
        self.stdout.write(f"""
        📊 Resumo:
        - Total de clientes: {stats['total']}
        - Nunca compraram: {stats['never_bought']}
        - Só abandonaram carrinho: {stats['abandoned_only']}
        - Clientes ativos: {stats['active']}
        """)