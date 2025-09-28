# customers/management/commands/debug_cart_data.py

from django.core.management.base import BaseCommand
from sshtunnel import SSHTunnelForwarder
import pymysql
import json
import os
from dotenv import load_dotenv
import phpserialize
from pprint import pprint

load_dotenv()

class Command(BaseCommand):
    help = 'Debug de dados do carrinho para identificar problemas'
    
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
    
    def parse_php_serialized(self, data):
        """Converte dados PHP serializados"""
        if not data:
            return None
        
        try:
            if isinstance(data, str):
                data = data.encode('utf-8', errors='ignore')
            
            unserialized = phpserialize.loads(data, decode_strings=True)
            return self.convert_to_python(unserialized)
        except Exception as e:
            return f"Erro: {e}"
    
    def convert_to_python(self, data):
        """Converte estruturas PHP para Python"""
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                if isinstance(key, bytes):
                    key = key.decode('utf-8', errors='ignore')
                result[str(key)] = self.convert_to_python(value)
            return result
        elif isinstance(data, (list, tuple)):
            return [self.convert_to_python(item) for item in data]
        elif isinstance(data, bytes):
            return data.decode('utf-8', errors='ignore')
        else:
            return data
    
    def handle(self, *args, **options):
        self.stdout.write('🔍 Analisando estrutura dos dados...')
        
        with SSHTunnelForwarder(
            (self.ssh_config['host'], 22),
            ssh_username=self.ssh_config['user'],
            ssh_pkey=self.ssh_config['key'],
            remote_bind_address=("127.0.0.1", 3306),
            local_bind_address=("127.0.0.1", 0),
        ) as tunnel:
            
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
                # Pegar amostra de carrinhos
                cursor.execute("""
                    SELECT cart_contents, checkout_id, email, cart_total, other_fields
                    FROM cli_cartflows_ca_cart_abandonment 
                    LIMIT 5
                """)
                
                samples = cursor.fetchall()
                
                for i, sample in enumerate(samples, 1):
                    self.stdout.write(f'\n{"="*60}')
                    self.stdout.write(f'📦 AMOSTRA {i}')
                    self.stdout.write(f'{"="*60}')
                    
                    self.stdout.write(f'Checkout ID: {sample["checkout_id"]}')
                    self.stdout.write(f'Email: {sample["email"]}')
                    self.stdout.write(f'Total: R$ {sample["cart_total"]}')
                    
                    # Analisar cart_contents
                    content = sample['cart_contents']
                    self.stdout.write(f'\n📋 CART_CONTENTS:')
                    self.stdout.write(f'Tipo: {type(content).__name__}')
                    
                    if content:
                        # Mostrar primeiros caracteres
                        preview = str(content)[:100]
                        self.stdout.write(f'Preview: {preview}...')
                        
                        # Identificar formato
                        if preview.startswith('a:'):
                            self.stdout.write(self.style.WARNING('📌 Formato: PHP Serializado'))
                            
                            # Tentar desserializar
                            parsed = self.parse_php_serialized(content)
                            if parsed and isinstance(parsed, dict):
                                self.stdout.write(self.style.SUCCESS('✅ Desserializado com sucesso!'))
                                
                                # Mostrar estrutura
                                self.stdout.write('\n🛒 Itens no carrinho:')
                                for key, item in parsed.items():
                                    if isinstance(item, dict):
                                        product_id = item.get('product_id', '?')
                                        quantity = item.get('quantity', '?')
                                        self.stdout.write(f'  - Produto ID: {product_id}, Qtd: {quantity}')
                            else:
                                self.stdout.write(self.style.ERROR(f'❌ Falha ao desserializar: {parsed}'))
                        
                        elif preview.startswith('{') or preview.startswith('['):
                            self.stdout.write('📌 Formato: Possível JSON')
                            try:
                                parsed = json.loads(content)
                                self.stdout.write(self.style.SUCCESS('✅ JSON válido'))
                            except:
                                self.stdout.write(self.style.ERROR('❌ JSON inválido'))
                        else:
                            self.stdout.write('📌 Formato: Desconhecido')
                    else:
                        self.stdout.write('⚠️ Conteúdo vazio')
                    
                    # Analisar other_fields
                    if sample['other_fields']:
                        self.stdout.write(f'\n📋 OTHER_FIELDS:')
                        other = self.parse_php_serialized(sample['other_fields'])
                        if other and isinstance(other, dict):
                            self.stdout.write('✅ Dados do cliente:')
                            for key in ['billing_first_name', 'billing_last_name', 'billing_phone', 'billing_email']:
                                if key in other:
                                    self.stdout.write(f'  - {key}: {other[key]}')
                
                # Estatísticas gerais
                self.stdout.write(f'\n{"="*60}')
                self.stdout.write('📊 ESTATÍSTICAS GERAIS')
                self.stdout.write(f'{"="*60}')
                
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total,
                        COUNT(DISTINCT email) as unique_emails,
                        SUM(CASE WHEN cart_contents IS NULL OR cart_contents = '' THEN 1 ELSE 0 END) as empty_carts,
                        AVG(cart_total) as avg_total
                    FROM cli_cartflows_ca_cart_abandonment
                """)
                
                stats = cursor.fetchone()
                self.stdout.write(f'Total de carrinhos: {stats["total"]}')
                self.stdout.write(f'Emails únicos: {stats["unique_emails"]}')
                self.stdout.write(f'Carrinhos vazios: {stats["empty_carts"]}')
                self.stdout.write(f'Valor médio: R$ {stats["avg_total"]:.2f}')
            
            conn.close()