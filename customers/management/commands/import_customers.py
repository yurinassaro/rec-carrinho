# customers/management/commands/import_customers.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import models
from datetime import datetime, timedelta
from sshtunnel import SSHTunnelForwarder
import pymysql
from customers.models import Customer, Cart, Order
import json
import os
from dotenv import load_dotenv
import phpserialize
import traceback

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
                
                # 3. Enriquecer dados com informações dos pedidos
                self.enrich_customer_data_from_orders(cursor)
                
                # 4. Enriquecer dados com informações do WordPress users
                self.enrich_customer_phone_data(cursor)
                
                # 5. Análise inteligente
                self.analyze_customers()
                
            conn.close()
    
    def custom_object_hook(self, obj):
        """
        Função: custom_object_hook
        Descrição: Hook customizado para lidar com objetos PHP
        Parâmetros:
            - obj: Objeto PHP serializado
        Retorno:
            - dict: Representação do objeto como dicionário
        """
        # Converter objeto PHP para dicionário Python
        if hasattr(obj, '__dict__'):
            return obj.__dict__
        return str(obj)
    
    def parse_php_serialized(self, data):
        """
        Função: parse_php_serialized
        Descrição: Converte dados PHP serializados para Python dict
        Parâmetros:
            - data (str/bytes): Dados serializados PHP
        Retorno:
            - dict: Dados convertidos ou dict vazio se falhar
        """
        if not data:
            return {}
        
        try:
            # Se for string, converter para bytes
            if isinstance(data, str):
                data = data.encode('utf-8', errors='ignore')
            
            # Desserializar com object_hook para lidar com objetos PHP
            unserialized = phpserialize.loads(
                data, 
                decode_strings=True,
                object_hook=self.custom_object_hook
            )
            
            # Converter para estrutura Python adequada
            return self.convert_php_to_python(unserialized)
            
        except Exception as e:
            # Se falhar com phpserialize, tentar uma abordagem mais simples
            try:
                # Tentar extrair dados básicos usando regex
                import re
                
                # Padrão para product_id
                product_ids = re.findall(r'"product_id";i:(\d+)', str(data))
                quantities = re.findall(r'"quantity";i:(\d+)', str(data))
                
                if product_ids:
                    items = []
                    for i, pid in enumerate(product_ids):
                        item = {
                            'product_id': int(pid),
                            'quantity': int(quantities[i]) if i < len(quantities) else 1
                        }
                        items.append(item)
                    
                    return {'items': items, 'extracted_via': 'regex'}
                
            except:
                pass
            
            self.stdout.write(
                self.style.WARNING(f'⚠️  Erro ao desserializar PHP: {str(e)[:100]}')
            )
            return {}
    
    def parse_wcf_fields(self, other_fields_data):
        """
        Função: parse_wcf_fields
        Descrição: Extrai dados dos campos WCF (WooCommerce CartFlows)
        Parâmetros:
            - other_fields_data: String com dados PHP serializados
        Retorno:
            - dict: Dados extraídos e organizados
        """
        customer_info = {}
        
        try:
            # Se for string, tentar decodificar
            if isinstance(other_fields_data, str):
                # Tentar JSON primeiro
                try:
                    data = json.loads(other_fields_data)
                except:
                    # Tentar PHP serializado
                    try:
                        data_bytes = other_fields_data.encode('utf-8', errors='ignore')
                        data = phpserialize.loads(
                            data_bytes,
                            decode_strings=True,
                            object_hook=lambda x: x.__dict__ if hasattr(x, '__dict__') else str(x)
                        )
                    except:
                        # Se falhar tudo, usar regex para extrair campos WCF
                        import re
                        
                        # Extrair telefone
                        phone_match = re.search(r'wcf_phone_number["\'].*;s:\d+:["\']([^"\']+)["\']', other_fields_data)
                        if phone_match:
                            customer_info['phone'] = phone_match.group(1)
                        
                        # Extrair nome
                        fname_match = re.search(r'wcf_first_name["\'].*;s:\d+:["\']([^"\']+)["\']', other_fields_data)
                        if fname_match:
                            customer_info['first_name'] = fname_match.group(1)
                        
                        lname_match = re.search(r'wcf_last_name["\'].*;s:\d+:["\']([^"\']+)["\']', other_fields_data)
                        if lname_match:
                            customer_info['last_name'] = lname_match.group(1)
                        
                        # Extrair endereço
                        addr_match = re.search(r'wcf_billing_address_1["\'].*;s:\d+:["\']([^"\']+)["\']', other_fields_data)
                        if addr_match:
                            customer_info['address'] = addr_match.group(1)
                        
                        city_match = re.search(r'wcf_billing_city["\'].*;s:\d+:["\']([^"\']+)["\']', other_fields_data)
                        if city_match:
                            customer_info['city'] = city_match.group(1)
                        
                        return customer_info
            else:
                data = other_fields_data
            
            # Se conseguiu decodificar como dict
            if isinstance(data, dict):
                # Mapear campos WCF para nosso modelo
                field_mapping = {
                    'wcf_phone_number': 'phone',
                    'wcf_billing_phone': 'phone',
                    'billing_phone': 'phone',
                    'wcf_first_name': 'first_name',
                    'wcf_billing_first_name': 'first_name',
                    'billing_first_name': 'first_name',
                    'wcf_last_name': 'last_name', 
                    'wcf_billing_last_name': 'last_name',
                    'billing_last_name': 'last_name',
                    'wcf_billing_address_1': 'address',
                    'wcf_billing_city': 'city',
                    'wcf_billing_state': 'state',
                    'wcf_billing_postcode': 'postcode'
                }
                
                for wcf_field, our_field in field_mapping.items():
                    if wcf_field in data and data[wcf_field]:
                        # Só sobrescrever telefone se ainda não tiver
                        if our_field == 'phone' and 'phone' in customer_info:
                            continue
                        customer_info[our_field] = data[wcf_field]
            
        except Exception as e:
            self.stdout.write(f'⚠️ Erro ao processar WCF fields: {e}')
        
        return customer_info
    
    def convert_php_to_python(self, data):
        """
        Função: convert_php_to_python
        Descrição: Converte estruturas PHP para Python recursivamente
        Parâmetros:
            - data: Dados desserializados do PHP
        Retorno:
            - Dados convertidos para estrutura Python nativa
        """
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                # Converter chave para string se for bytes
                if isinstance(key, bytes):
                    key = key.decode('utf-8', errors='ignore')
                result[str(key)] = self.convert_php_to_python(value)
            return result
        elif isinstance(data, (list, tuple)):
            return [self.convert_php_to_python(item) for item in data]
        elif isinstance(data, bytes):
            return data.decode('utf-8', errors='ignore')
        else:
            return data
    
    def parse_cart_contents_simple(self, cart_data):
        """
        Função: parse_cart_contents_simple
        Descrição: Extração simplificada de dados do carrinho
        Parâmetros:
            - cart_data (dict): Dados do carrinho do banco
        Retorno:
            - dict: Conteúdo do carrinho processado
        """
        cart_contents_raw = cart_data.get('cart_contents', '')
        
        if not cart_contents_raw:
            return {'items': [], 'total_items': 0}
        
        # Converter para string se necessário
        if isinstance(cart_contents_raw, bytes):
            cart_contents_raw = cart_contents_raw.decode('utf-8', errors='ignore')
        
        cart_contents_str = str(cart_contents_raw)
        
        # Usar regex para extrair informações essenciais
        import re
        
        items = []
        
        # Extrair product_ids
        product_matches = re.findall(r'"product_id";i:(\d+)', cart_contents_str)
        variation_matches = re.findall(r'"variation_id";i:(\d+)', cart_contents_str)
        quantity_matches = re.findall(r'"quantity";[i|d]:(\d+)', cart_contents_str)
        
        # Montar itens
        for i in range(len(product_matches)):
            item = {
                'product_id': int(product_matches[i]) if i < len(product_matches) else 0,
                'variation_id': int(variation_matches[i]) if i < len(variation_matches) else 0,
                'quantity': int(quantity_matches[i]) if i < len(quantity_matches) else 1,
            }
            items.append(item)
        
        total_items = sum(item['quantity'] for item in items)
        
        return {
            'items': items,
            'total_items': total_items,
            'method': 'regex_extraction'
        }
    
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
        
        # Contadores
        success_count = 0
        error_count = 0
        skip_count = 0
        
        for cart_data in carts:
            try:
                # Validar email
                if not cart_data.get('email'):
                    skip_count += 1
                    continue
                
                # Criar ou atualizar cliente
                customer_data = {
                    'email': cart_data['email']
                }
                
                # Processar other_fields (CORREÇÃO AQUI)
                if cart_data.get('other_fields'):
                    wcf_data = self.parse_wcf_fields(cart_data['other_fields'])
                    
                    if wcf_data:  # INDENTAÇÃO CORRIGIDA
                        # Atualizar dados do cliente
                        if wcf_data.get('phone'):
                            customer_data['phone'] = wcf_data['phone']
                        if wcf_data.get('first_name'):
                            customer_data['first_name'] = wcf_data['first_name']
                        if wcf_data.get('last_name'):
                            customer_data['last_name'] = wcf_data['last_name']
                        
                        # Debug - mostrar quando encontrar telefone
                        if wcf_data.get('phone'):
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f'  📱 {cart_data["email"]}: {wcf_data["phone"]}'
                                )
                            )
                
                customer, created = Customer.objects.update_or_create(
                    email=cart_data['email'],
                    defaults=customer_data
                )
                
                # Usar método simplificado para processar carrinho
                cart_contents = self.parse_cart_contents_simple(cart_data)
                
                # Calcular total de itens
                items_count = len(cart_contents.get('items', []))
                
                # Processar cart_total
                try:
                    cart_total = float(cart_data.get('cart_total', 0) or 0)
                except (ValueError, TypeError):
                    cart_total = 0.0
                
                # Criar ou atualizar carrinho
                Cart.objects.update_or_create(
                    checkout_id=cart_data['checkout_id'],
                    defaults={
                        'customer': customer,
                        'session_id': cart_data.get('session_id', ''),
                        'cart_contents': cart_contents,
                        'cart_total': cart_total,
                        'items_count': items_count,
                        'status': 'abandoned' if cart_data.get('order_status') == 'abandoned' else 'active',
                        'created_at': cart_data.get('time'),
                    }
                )
                
                # Atualizar estatísticas do cliente
                from django.db.models import Sum, Count, Q
                
                cart_stats = customer.carts.aggregate(
                    total=Count('id'),
                    abandoned=Count('id', filter=Q(status='abandoned')),
                    total_value=Sum('cart_total', filter=Q(status='abandoned'))
                )
                
                customer.total_carts = cart_stats['total'] or 0
                customer.abandoned_carts = cart_stats['abandoned'] or 0
                customer.total_abandoned_value = cart_stats['total_value'] or 0
                
                # Atualizar first_seen
                if cart_data.get('time'):
                    # Garantir que ambas as datas tenham timezone
                    cart_time = cart_data['time']
                    if cart_time:  # Verificar se não é None
                        if not hasattr(cart_time, 'tzinfo') or not cart_time.tzinfo:
                            cart_time = timezone.make_aware(cart_time)
                        
                        if not customer.first_seen or cart_time < customer.first_seen:
                            customer.first_seen = cart_time
                
                # CORREÇÃO: Salvar cliente após todas as atualizações
                customer.save()
                success_count += 1
                
                # Progresso
                if success_count % 100 == 0:
                    self.stdout.write(f'✅ {success_count} carrinhos processados...')
                    
            except Exception as e:
                error_count += 1
                if error_count <= 5:  # Mostrar apenas os primeiros 5 erros detalhados
                    self.stdout.write(
                        self.style.ERROR(
                            f'❌ Erro no carrinho {cart_data.get("checkout_id", "?")}:\n{traceback.format_exc()}'
                        )
                    )
                continue
        
        # Relatório final
        self.stdout.write(
            self.style.SUCCESS(
                f'\n📊 Importação de carrinhos concluída:\n'
                f'  ✅ Sucesso: {success_count}\n'
                f'  ⚠️  Ignorados: {skip_count}\n'
                f'  ❌ Erros: {error_count}\n'
                f'  📦 Total: {len(carts)}'
            )
        )
    
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
        
        success_count = 0
        for order_data in orders:
            try:
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
                success_count += 1
            except Exception as e:
                self.stdout.write(f'❌ Erro no pedido {order_data.get("order_id")}: {e}')
        
        self.stdout.write(f'✅ {success_count} pedidos importados')
    
    # BUSCANDO TELEFONE DOS CLIENTES
    def analyze_customers(self):
        """Análise inteligente de clientes"""
        
        self.stdout.write('🧠 Executando análise inteligente...')
        
        from django.db.models import Sum, Count
        
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
        
            # Última compra
            if customer.last_purchase:
                last_activities.append(customer.last_purchase)
            
            # Último carrinho abandonado (pegar a data mais recente dos carrinhos)
            last_cart = customer.carts.filter(
                created_at__isnull=False
            ).order_by('-created_at').first()
            
            if last_cart and last_cart.created_at:
                last_activities.append(last_cart.created_at)
                
                # Também atualizar last_cart_abandoned se for abandonado
                if last_cart.status == 'abandoned':
                    customer.last_cart_abandoned = last_cart.created_at
            
            # Definir última atividade
            if last_activities:
                customer.last_activity = max(last_activities)
            # Se não houver nenhuma atividade registrada, usar first_seen
            elif customer.first_seen:
                customer.last_activity = customer.first_seen
            # Apenas como último recurso, usar data atual
            else:
                customer.last_activity = timezone.now()
            
            # Salvar
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
        📊 Resumo Final:
        - Total de clientes: {stats['total']}
        - Nunca compraram: {stats['never_bought']}
        - Só abandonaram carrinho: {stats['abandoned_only']}
        - Clientes ativos: {stats['active']}
        """)

    def enrich_customer_phone_data(self, cursor):
        """
        Função: enrich_customer_phone_data
        Descrição: Busca telefones dos clientes no WordPress users/usermeta
        Parâmetros:
            - cursor: Cursor MySQL
        Retorno:
            - None (atualiza clientes diretamente)
        """
        self.stdout.write('📱 Buscando telefones dos usuários WordPress...')
        
        # Descobrir prefixo das tabelas
        cursor.execute("SHOW TABLES LIKE '%users'")
        tables = cursor.fetchall()
        
        if not tables:
            self.stdout.write('❌ Tabela users não encontrada')
            return
        
        users_table = list(tables[0].values())[0]
        prefix = users_table.replace('users', '')
        
        # Query para buscar telefones de várias fontes possíveis
        query = f"""
        SELECT DISTINCT
            u.user_email as email,
            u.ID as user_id,
            u.display_name,
            COALESCE(
                um_billing_phone.meta_value,
                um_phone.meta_value,
                um_billing_cellphone.meta_value,
                um_shipping_phone.meta_value,  
                um_billing_phone_number.meta_value,
                um_digits_phone.meta_value
            ) as phone,
            um_first_name.meta_value as first_name,
            um_last_name.meta_value as last_name,
            um_billing_first_name.meta_value as billing_first_name,
            um_billing_last_name.meta_value as billing_last_name,
            um_billing_address_1.meta_value as address_1,
            um_billing_city.meta_value as city,
            um_billing_state.meta_value as state,
            um_billing_postcode.meta_value as postcode
        FROM {users_table} u
        LEFT JOIN {prefix}usermeta um_billing_phone 
            ON u.ID = um_billing_phone.user_id 
            AND um_billing_phone.meta_key = 'billing_phone'
        LEFT JOIN {prefix}usermeta um_billing_cellphone 
            ON u.ID = um_billing_cellphone.user_id 
            AND um_billing_cellphone.meta_key = 'billing_cellphone'
        LEFT JOIN {prefix}usermeta um_shipping_phone 
            ON u.ID = um_shipping_phone.user_id 
            AND um_shipping_phone.meta_key = 'shipping_phone'
        LEFT JOIN {prefix}usermeta um_phone 
            ON u.ID = um_phone.user_id 
            AND um_phone.meta_key = 'phone'
        LEFT JOIN {prefix}usermeta um_billing_phone_number 
            ON u.ID = um_billing_phone_number.user_id 
            AND um_billing_phone_number.meta_key = 'billing_phone_number'
        LEFT JOIN {prefix}usermeta um_digits_phone 
            ON u.ID = um_digits_phone.user_id 
            AND um_digits_phone.meta_key = 'digits_phone'
        LEFT JOIN {prefix}usermeta um_first_name 
            ON u.ID = um_first_name.user_id 
            AND um_first_name.meta_key = 'first_name'
        LEFT JOIN {prefix}usermeta um_last_name 
            ON u.ID = um_last_name.user_id 
            AND um_last_name.meta_key = 'last_name'
        LEFT JOIN {prefix}usermeta um_billing_first_name 
            ON u.ID = um_billing_first_name.user_id 
            AND um_billing_first_name.meta_key = 'billing_first_name'
        LEFT JOIN {prefix}usermeta um_billing_last_name 
            ON u.ID = um_billing_last_name.user_id 
            AND um_billing_last_name.meta_key = 'billing_last_name'
        LEFT JOIN {prefix}usermeta um_billing_address_1 
            ON u.ID = um_billing_address_1.user_id 
            AND um_billing_address_1.meta_key = 'billing_address_1'
        LEFT JOIN {prefix}usermeta um_billing_city 
            ON u.ID = um_billing_city.user_id 
            AND um_billing_city.meta_key = 'billing_city'
        LEFT JOIN {prefix}usermeta um_billing_state 
            ON u.ID = um_billing_state.user_id 
            AND um_billing_state.meta_key = 'billing_state'
        LEFT JOIN {prefix}usermeta um_billing_postcode 
            ON u.ID = um_billing_postcode.user_id 
            AND um_billing_postcode.meta_key = 'billing_postcode'
        WHERE u.user_email != ''
        """
        
        cursor.execute(query)
        users_data = cursor.fetchall()
        
        self.stdout.write(f'📊 Encontrados {len(users_data)} usuários no WordPress')
        
        updated_count = 0
        for user_data in users_data:
            try:
                # Buscar cliente pelo email
                customer = Customer.objects.filter(email=user_data['email']).first()
                
                if customer:
                    updated = False
                    
                    # Atualizar telefone se não tiver
                    if not customer.phone and user_data['phone']:
                        customer.phone = user_data['phone']
                        updated = True
                    
                    # Atualizar nome se não tiver
                    if not customer.first_name:
                        customer.first_name = (
                            user_data['billing_first_name'] or 
                            user_data['first_name'] or 
                            ''
                        )
                        updated = True
                    
                    if not customer.last_name:
                        customer.last_name = (
                            user_data['billing_last_name'] or 
                            user_data['last_name'] or 
                            ''
                        )
                        updated = True
                    
                    # Adicionar informações extras como tags
                    if user_data['city'] or user_data['state']:
                        location_info = {
                            'city': user_data['city'],
                            'state': user_data['state'],
                            'postcode': user_data['postcode']
                        }
                        if 'location' not in customer.tags:
                            customer.tags.append(location_info)
                            updated = True
                    
                    if updated:
                        customer.save()
                        updated_count += 1
                        
            except Exception as e:
                self.stdout.write(f'❌ Erro ao atualizar {user_data["email"]}: {e}')
        
        self.stdout.write(f'✅ {updated_count} clientes atualizados com dados do WordPress')

    def enrich_customer_data_from_orders(self, cursor):
        """
        Função: enrich_customer_data_from_orders
        Descrição: Enriquece dados dos clientes com informações dos pedidos
        Parâmetros:
            - cursor: Cursor MySQL
        Retorno:
            - None (atualiza clientes diretamente)
        """
        self.stdout.write('📞 Buscando telefones nos pedidos WooCommerce...')
        
        # Descobrir prefixo das tabelas
        cursor.execute("SHOW TABLES LIKE '%posts'")
        tables = cursor.fetchall()
        
        if not tables:
            return
        
        posts_table = list(tables[0].values())[0]
        prefix = posts_table.replace('posts', '')
        
        # Query para buscar todos os dados de billing dos pedidos
        query = f"""
        SELECT DISTINCT
            pm_email.meta_value as email,
            pm_phone.meta_value as phone,
            pm_fname.meta_value as first_name,
            pm_lname.meta_value as last_name,
            pm_address_1.meta_value as address_1,
            pm_city.meta_value as city,
            pm_state.meta_value as state,
            pm_postcode.meta_value as postcode,
            p.ID as order_id,
            p.post_date as order_date
        FROM {posts_table} p
        LEFT JOIN {prefix}postmeta pm_email ON p.ID = pm_email.post_id 
            AND pm_email.meta_key = '_billing_email'
        LEFT JOIN {prefix}postmeta pm_phone ON p.ID = pm_phone.post_id 
            AND pm_phone.meta_key = '_billing_phone'
        LEFT JOIN {prefix}postmeta pm_fname ON p.ID = pm_fname.post_id 
            AND pm_fname.meta_key = '_billing_first_name'
        LEFT JOIN {prefix}postmeta pm_lname ON p.ID = pm_lname.post_id 
            AND pm_lname.meta_key = '_billing_last_name'
        LEFT JOIN {prefix}postmeta pm_address_1 ON p.ID = pm_address_1.post_id 
            AND pm_address_1.meta_key = '_billing_address_1'
        LEFT JOIN {prefix}postmeta pm_city ON p.ID = pm_city.post_id 
            AND pm_city.meta_key = '_billing_city'
        LEFT JOIN {prefix}postmeta pm_state ON p.ID = pm_state.post_id 
            AND pm_state.meta_key = '_billing_state'
        LEFT JOIN {prefix}postmeta pm_postcode ON p.ID = pm_postcode.post_id 
            AND pm_postcode.meta_key = '_billing_postcode'
        WHERE p.post_type = 'shop_order'
        AND pm_email.meta_value IS NOT NULL
        AND pm_phone.meta_value IS NOT NULL
        AND pm_phone.meta_value != ''
        ORDER BY p.post_date DESC
        """
        
        cursor.execute(query)
        orders_data = cursor.fetchall()
        
        self.stdout.write(f'📊 Encontrados {len(orders_data)} pedidos com telefone')
        
        # Agrupar por email para pegar o telefone mais recente
        customer_phones = {}
        for order in orders_data:
            email = order['email']
            if email and order['phone']:
                # Se ainda não temos o telefone deste email ou este pedido é mais recente
                if email not in customer_phones or order['order_date'] > customer_phones[email]['date']:
                    customer_phones[email] = {
                        'phone': order['phone'],
                        'first_name': order['first_name'],
                        'last_name': order['last_name'],
                        'city': order['city'],
                        'state': order['state'],
                        'date': order['order_date']
                    }
        
        # Atualizar clientes
        updated_count = 0
        for email, data in customer_phones.items():
            try:
                customers = Customer.objects.filter(email=email)
                for customer in customers:
                    updated = False
                    
                    # Atualizar telefone se não tiver
                    if not customer.phone and data['phone']:
                        customer.phone = data['phone']
                        updated = True
                        self.stdout.write(f'  ✅ {email}: {data["phone"]}')
                    
                    # Atualizar nome se não tiver
                    if not customer.first_name and data['first_name']:
                        customer.first_name = data['first_name']
                        updated = True
                    
                    if not customer.last_name and data['last_name']:
                        customer.last_name = data['last_name']
                        updated = True
                    
                    if updated:
                        customer.save()
                        updated_count += 1
                        
            except Exception as e:
                self.stdout.write(f'❌ Erro ao atualizar {email}: {e}')
        
        self.stdout.write(f'✅ {updated_count} clientes atualizados com dados dos pedidos')