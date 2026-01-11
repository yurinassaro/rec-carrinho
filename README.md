# Carrinho e Leads

Sistema multi-tenant para gestao de leads e recuperacao de carrinhos abandonados do WooCommerce.

## Funcionalidades

### Gestao de Leads (Form Vibes)
- Importacao de leads do plugin Form Vibes (WordPress)
- Campos configuraveis por empresa (nome, whatsapp, tamanho)
- Verificacao automatica se lead ja e cliente
- Exportacao para WhatsApp/Excel/TXT
- Dashboard com estatisticas em tempo real
- Botao de acao para enviar WhatsApp

### Carrinhos Abandonados
- Importacao de carrinhos do plugin Cart Recovery (WooCommerce)
- Analise de recuperacao (janela: 2 dias antes ate 30 dias depois)
- Cruzamento por email E telefone
- Status: abandonado, recuperado, aguardando
- Toggle de email/WhatsApp enviado
- Taxa de recuperacao automatica

### Pedidos
- Importacao de pedidos do WooCommerce
- Vinculacao com clientes e carrinhos
- Analise de ticket medio e recorrencia

### Multi-Tenant
- Suporte a multiplas empresas
- Isolamento total de dados por empresa
- Configuracoes individuais de conexao e campos Form Vibes

### Importacao em Background
- Celery para processamento assincrono
- Progresso em tempo real via Redis
- Resumo formatado ao final

---

## Stack Tecnologica

- **Backend**: Django 4.2 + Django REST Framework
- **Banco de Dados**: PostgreSQL
- **Cache/Broker**: Redis
- **Tasks**: Celery
- **Servidor**: Nginx + Gunicorn
- **Container**: Docker Compose

---

## Hospedagem

### Servidor de Producao
- **IP**: 143.110.150.237
- **SSH**: `root@143.110.150.237`
- **Caminho**: `/var/www/customer-intelligence`
- **Dominio**: leads.posvendafacil.com.br

### Containers Docker
| Container | Servico |
|-----------|---------|
| leads_web | Django/Gunicorn |
| leads_celery | Celery Worker |
| leads_db | PostgreSQL |
| leads_redis | Redis |
| leads_nginx | Nginx |

---

## Empresas Configuradas

### Tarragona
- **Slug**: `tarragona`
- **Conexao**: SSH Tunnel
- **SSH Host**: 157.245.119.130
- **DB Name**: tarr_tarragona
- **Form Vibes**: Nome_3, Whatsapp_8, Numero_do_sapato_9

### ANAC Deluxe
- **Slug**: `anacdeluxe`
- **Conexao**: Direta (Hostinger)
- **DB Host**: srv1888.hstgr.io
- **DB Name**: u132080491_anadeluxe
- **Form Vibes**: Nome_3, Whatsapp_-_DDD_+_Numero_4

---

## Instalacao Local

### Pre-requisitos
- Python 3.12+
- PostgreSQL
- Redis

### Setup
```bash
# Clonar repositorio
git clone <repo-url>
cd customer-intelligence

# Criar ambiente virtual
python -m venv .venv
source .venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt

# Configurar .env
cp .env.example .env
# Editar .env com suas configuracoes

# Rodar migrations
python manage.py migrate

# Criar superusuario
python manage.py createsuperuser

# Rodar servidor
python manage.py runserver
```

### Rodar Celery (em outro terminal)
```bash
celery -A customer_intelligence worker -l info
```

---

## Deploy em Producao

### Sincronizar arquivos
```bash
rsync -avz --relative \
  [arquivos] \
  root@143.110.150.237:/var/www/customer-intelligence/
```

### Aplicar migrations
```bash
ssh root@143.110.150.237 "cd /var/www/customer-intelligence && \
  docker compose -f docker-compose.prod.yml exec web python manage.py migrate"
```

### Reiniciar servicos
```bash
ssh root@143.110.150.237 "cd /var/www/customer-intelligence && \
  docker compose -f docker-compose.prod.yml restart web celery"
```

### Comandos uteis
```bash
# Logs
./deploy.sh logs          # Web
./deploy.sh logs celery   # Celery
./deploy.sh logs nginx    # Nginx

# Shell Django
./deploy.sh shell

# Backup
./deploy.sh backup

# Importar dados
./deploy.sh import tarragona 2024-01-01 2024-12-31
./deploy.sh import anacdeluxe 2024-01-01 2024-12-31
```

---

## Comandos de Importacao

### Importar Carrinhos e Pedidos
```bash
# Importacao completa (historico)
python manage.py import_customers --empresa=tarragona \
  --start_date=2024-01-01 --end_date=2024-12-31 --import_type=all

# Ultimos 7 dias
python manage.py import_customers --empresa=tarragona \
  --start_date=2024-12-24 --end_date=2024-12-31 --import_type=all

# Apenas verificar recuperacoes
python manage.py import_customers --empresa=tarragona --import_type=orders --check_recovery
```

### Importar Leads
```bash
# Por periodo
python manage.py import_leads --empresa=anacdeluxe \
  --start_date=2024-01-01 --end_date=2024-12-31

# Periodo predefinido
python manage.py import_leads --empresa=tarragona --periodo=7dias
```

---

## Configuracao Form Vibes

Cada empresa pode ter campos diferentes no formulario. Configure em:
**Admin > Tenants > Empresas > [Empresa] > Form Vibes - Mapeamento de Campos**

| Campo | Descricao | Exemplo Tarragona | Exemplo ANAC |
|-------|-----------|-------------------|--------------|
| fv_field_nome | Campo do nome | Nome_3 | Nome_3 |
| fv_field_whatsapp | Campo do WhatsApp | Whatsapp_8 | Whatsapp_-_DDD_+_Numero_4 |
| fv_field_tamanho | Campo do tamanho | Numero_do_sapato_9 | (vazio) |

**Nota**: O Form Vibes converte espacos para underscores e adiciona sufixo numerico.

---

## Estrutura do Projeto

```
customer-intelligence/
├── customer_intelligence/    # Configuracoes Django
│   ├── settings.py
│   ├── urls.py
│   └── celery.py
├── customers/                # App principal
│   ├── models.py            # Customer, Cart, Order, Lead
│   ├── admin.py             # Interface admin
│   └── management/commands/ # Comandos de importacao
├── importer/                 # Dashboard de importacao
│   ├── views.py
│   ├── tasks.py             # Tasks Celery
│   └── templates/
├── tenants/                  # Multi-tenant
│   ├── models.py            # Empresa, EmpresaUsuario
│   └── middleware.py
├── analytics/                # Relatorios (futuro)
├── docker-compose.yml        # Dev
├── docker-compose.prod.yml   # Producao
└── deploy.sh                 # Script de deploy
```

---

## API REST

### Endpoints
- `GET /api/customers/` - Lista clientes
- `GET /api/customers/{id}/` - Detalhe cliente
- `GET /health/` - Health check

### Autenticacao
API usa autenticacao por sessao (Django Admin).

---

## Troubleshooting

### Leads nao importando
1. Verificar nome dos campos no banco:
```sql
SELECT DISTINCT meta_key FROM cli_fv_entry_meta;
```
2. Atualizar configuracao da empresa no admin

### Conexao recusada (ANAC/Hostinger)
1. Verificar se IP do servidor esta liberado na Hostinger
2. IP atual: 143.110.150.237

### Carrinhos sem telefone
- O sistema busca telefone na tabela `cli_woo_cart_abandonment`
- Campo: `phone`

---

## Contato

Desenvolvido por Cliente
