from django.core.management.base import BaseCommand
from sshtunnel import SSHTunnelForwarder
import pymysql
import os
from dotenv import load_dotenv

load_dotenv()

class Command(BaseCommand):
    help = 'Verifica onde estão os telefones no banco WordPress'
    
    def handle(self, *args, **options):
        ssh_config = {
            'host': os.getenv('SSH_HOST'),
            'user': os.getenv('SSH_USER'),
            'key': os.getenv('SSH_KEY'),
        }
        
        db_config = {
            'user': os.getenv('WOO_DB_USER'),
            'password': os.getenv('WOO_DB_PASS'),
            'database': os.getenv('WOO_DB_NAME'),
        }
        
        with SSHTunnelForwarder(
            (ssh_config['host'], 22),
            ssh_username=ssh_config['user'],
            ssh_pkey=ssh_config['key'],
            remote_bind_address=("127.0.0.1", 3306),
            local_bind_address=("127.0.0.1", 0),
        ) as tunnel:
            
            conn = pymysql.connect(
                host="127.0.0.1",
                port=tunnel.local_bind_port,
                user=db_config['user'],
                password=db_config['password'],
                database=db_config['database'],
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
            )
            
            with conn.cursor() as cursor:
                # Buscar telefone do Giovanni especificamente
                email = 'gioacs@uol.com.br'
                
                # Checar na tabela users
                cursor.execute("SHOW TABLES LIKE '%usermeta%'")
                tables = cursor.fetchall()
                
                if tables:
                    table_name = list(tables[0].values())[0]
                    
                    # Buscar todos os meta_keys que contém 'phone'
                    cursor.execute(f"""
                        SELECT DISTINCT meta_key 
                        FROM {table_name}
                        WHERE meta_key LIKE '%phone%' 
                           OR meta_key LIKE '%tel%'
                           OR meta_key LIKE '%celular%'
                           OR meta_key LIKE '%mobile%'
                    """)
                    
                    phone_fields = cursor.fetchall()
                    self.stdout.write('\n📱 Campos de telefone encontrados:')
                    for field in phone_fields:
                        self.stdout.write(f'  - {field["meta_key"]}')
                    
                    # Buscar dados do Giovanni
                    prefix = table_name.replace('usermeta', '')
                    # DEPOIS (corrigido):
                    cursor.execute(f"""
                        SELECT u.user_email, um.*
                        FROM {prefix}users u
                        JOIN {table_name} um ON u.ID = um.user_id
                        WHERE u.user_email = %s
                        AND (um.meta_key LIKE '%%phone%%' 
                            OR um.meta_key LIKE '%%first%%' 
                            OR um.meta_key LIKE '%%last%%')
                    """, (email,))
                    
                    giovanni_data = cursor.fetchall()
                    
                    self.stdout.write(f'\n👤 Dados encontrados para {email}:')
                    for data in giovanni_data:
                        self.stdout.write(f'  {data["meta_key"]}: {data["meta_value"]}')
            
            conn.close()