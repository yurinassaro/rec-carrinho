# customers/management/commands/import_leads.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, timedelta
from sshtunnel import SSHTunnelForwarder
import pymysql
from customers.models import Lead, Customer
import os
from dotenv import load_dotenv

load_dotenv()

class Command(BaseCommand):
    help = 'Importa leads do Form Vibes'
    
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
    
    def add_arguments(self, parser):
        parser.add_argument('--start_date', type=str, help='Data inicial (YYYY-MM-DD)')
        parser.add_argument('--end_date', type=str, help='Data final (YYYY-MM-DD)')
        parser.add_argument('--periodo', type=str,
                          choices=['ontem', '7dias', '30dias', 'mes_atual'],
                          help='Período predefinido')
    
    def handle(self, *args, **options):
        """
        Função: handle
        Descrição: Processa a importação de leads com filtros de data
        Parâmetros:
          - args: argumentos posicionais
          - options: opções do comando (periodo, start_date, end_date)
        Retorno: nenhum
        """
        # Processar datas
        if options.get('periodo'):
            start_date, end_date = self.get_periodo_dates(options['periodo'])
        elif options.get('start_date') and options.get('end_date'):
            start_date = datetime.strptime(options['start_date'], '%Y-%m-%d')
            end_date = datetime.strptime(options['end_date'], '%Y-%m-%d')
        else:
            # Padrão: últimos 30 dias
            end_date = datetime.now()
            start_date = end_date - timedelta(days=30)
        
        end_date = end_date.replace(hour=23, minute=59, second=59)
        
        self.stdout.write(
            f'📋 Importando leads do Form Vibes\n'
            f'Período: {start_date.strftime("%d/%m/%Y")} até {end_date.strftime("%d/%m/%Y")}'
        )
        
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
                self.import_form_leads(cursor, start_date, end_date)
            
            conn.close()
    
    def get_periodo_dates(self, periodo):
        """
        Função: get_periodo_dates
        Descrição: Calcula datas baseado no período selecionado
        Parâmetros:
          - periodo (str): 'ontem', '7dias', '30dias' ou 'mes_atual'
        Retorno:
          - tuple: (datetime start, datetime end)
        """
        today = datetime.now()
        
        if periodo == 'ontem':
            start = today - timedelta(days=1)
            start = start.replace(hour=0, minute=0, second=0)
            end = start.replace(hour=23, minute=59, second=59)
        elif periodo == '7dias':
            start = today - timedelta(days=7)
            end = today
        elif periodo == '30dias':
            start = today - timedelta(days=30)
            end = today
        elif periodo == 'mes_atual':
            start = today.replace(day=1, hour=0, minute=0, second=0)
            end = today
        
        return start, end
    
    def discover_table_prefix(self, cursor):
        """
        Função: discover_table_prefix
        Descrição: Descobre o prefixo das tabelas do Form Vibes
        Parâmetros:
          - cursor: cursor MySQL
        Retorno:
          - str: prefixo das tabelas (ex: 'cli_', 'wp_', etc)
        """
        # Buscar tabela do Form Vibes
        cursor.execute("""
            SHOW TABLES LIKE '%fv_enteries%'
        """)
        
        result = cursor.fetchone()
        if not result:
            # Tentar com entries (sem o erro de digitação)
            cursor.execute("""
                SHOW TABLES LIKE '%fv_entries%'
            """)
            result = cursor.fetchone()
        
        if not result:
            raise Exception("Tabelas do Form Vibes não encontradas no banco de dados")
        
        # Extrair o nome da tabela
        table_name = list(result.values())[0]
        
        # Extrair o prefixo (tudo antes de 'fv_')
        prefix = table_name.split('fv_')[0]
        
        self.stdout.write(f'✅ Prefixo detectado: {prefix}')
        self.stdout.write(f'📊 Tabela encontrada: {table_name}')
        
        return prefix, table_name
    
    def import_form_leads(self, cursor, start_date, end_date):
        """
        Função: import_form_leads
        Descrição: Importa TODOS os leads do banco Form Vibes (sem filtro de número)
        Parâmetros:
          - cursor: cursor MySQL
          - start_date (datetime): data inicial
          - end_date (datetime): data final
        Retorno: nenhum
        """
        
        # Descobrir prefixo das tabelas
        try:
            prefix, entries_table = self.discover_table_prefix(cursor)
            meta_table = f"{prefix}fv_entry_meta"
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Erro ao descobrir tabelas: {e}'))
            return
        
        # Query usando as tabelas descobertas - IMPORTA TODOS OS LEADS
        query = f"""
        SELECT
            e.id AS lead_id,
            e.captured AS data_captura,
            e.captured_gmt,
            e.url,
            e.user_agent,
            e.form_id,
            e.form_plugin,
            MAX(CASE WHEN m.meta_key = 'Nome_3' THEN m.meta_value END) AS nome,
            MAX(CASE WHEN m.meta_key = 'Whatsapp_8' THEN m.meta_value END) AS whatsapp,
            MAX(CASE WHEN m.meta_key = 'Número_do_sapato_9' THEN m.meta_value END) AS numero_sapato,
            MAX(CASE WHEN m.meta_key = 'IP' THEN m.meta_value END) AS ip
        FROM {entries_table} e
        LEFT JOIN {meta_table} m ON e.id = m.data_id
        WHERE e.captured BETWEEN %s AND %s
        GROUP BY e.id
        ORDER BY e.captured DESC
        """

        self.stdout.write(f'🔍 Buscando TODOS os leads entre {start_date.strftime("%d/%m/%Y")} e {end_date.strftime("%d/%m/%Y")}')
        self.stdout.write(f'📌 Nota: Importação não filtra por número de sapato')

        cursor.execute(query, (
            start_date.strftime('%Y-%m-%d %H:%M:%S'),
            end_date.strftime('%Y-%m-%d %H:%M:%S')
        ))
        
        leads_data = cursor.fetchall()
        
        self.stdout.write(f'📥 Encontrados {len(leads_data)} leads no período')
        
        new_leads = 0
        existing_customers = 0
        updated_leads = 0
        
        for data in leads_data:
            try:
                # Processar dados
                nome = (data['nome'] or '').strip()
                whatsapp = (data['whatsapp'] or '').strip()
                numero_sapato = (data['numero_sapato'] or '').strip()
                
                # Pular se não tiver dados mínimos
                if not nome and not whatsapp:
                    self.stdout.write(f'⚠️  Lead {data["lead_id"]} sem nome ou WhatsApp, pulando...')
                    continue
                
                # Verificar se já existe
                lead, created = Lead.objects.update_or_create(
                    form_id=str(data['lead_id']),
                    defaults={
                        'nome': nome,
                        'whatsapp': whatsapp,
                        'numero_sapato': numero_sapato,
                        'ip_address': data['ip'] or '',
                        'created_at': data['data_captura']
                    }
                )
                
                if created:
                    new_leads += 1
                    # Verificar se já é cliente
                    if lead.check_if_customer():
                        existing_customers += 1
                        self.stdout.write(
                            self.style.SUCCESS(f'  ✅ {lead.nome} - JÁ É CLIENTE!')
                        )
                    else:
                        self.stdout.write(
                            f'  📱 {lead.nome} - Novo lead - Sapato {lead.numero_sapato}'
                        )
                else:
                    updated_leads += 1
                    self.stdout.write(f'  🔄 {lead.nome} - Atualizado')
                
                lead.save()
                
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'❌ Erro no lead {data.get("lead_id")}: {e}')
                )
        
        # Resumo final
        self.stdout.write(
            self.style.SUCCESS(
                f'\n{"="*50}\n'
                f'📊 RESUMO DA IMPORTAÇÃO:\n'
                f'{"="*50}\n'
                f'  ✨ Novos leads: {new_leads}\n'
                f'  👥 Já são clientes: {existing_customers}\n'
                f'  🔄 Atualizados: {updated_leads}\n'
                f'  📈 Taxa de clientes: {(existing_customers/new_leads*100 if new_leads else 0):.1f}%\n'
                f'{"="*50}'
            )
        )