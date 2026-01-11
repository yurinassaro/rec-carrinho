# Deploy - Customer Intelligence

## Pre-requisitos no Servidor

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install -y docker.io docker-compose git

# Iniciar Docker
sudo systemctl enable docker
sudo systemctl start docker

# Adicionar usuario ao grupo docker
sudo usermod -aG docker $USER
```

## 1. Clonar/Enviar Projeto

```bash
# No servidor
cd /opt
git clone <seu-repo> customer-intelligence
cd customer-intelligence

# Ou enviar via rsync
rsync -avz --exclude '.venv' --exclude '__pycache__' \
    ./ usuario@servidor:/opt/customer-intelligence/
```

## 2. Configurar DNS

No painel de DNS do dominio posvendafacil.com.br, adicionar:

```
Tipo: A
Nome: leads
Valor: IP_DO_SERVIDOR
TTL: 300
```

## 3. Configurar Ambiente

```bash
cd /opt/customer-intelligence

# Copiar e editar configuracao
cp .env.production.example .env.production
nano .env.production
```

Configurar:
- `SECRET_KEY`: Gerar com `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`
- `POSTGRES_PASSWORD`: Senha segura
- `ALLOWED_HOSTS`: leads.posvendafacil.com.br
- `CSRF_TRUSTED_ORIGINS`: https://leads.posvendafacil.com.br

## 4. Configurar Chaves SSH (para WooCommerce)

```bash
# Criar diretorio para chaves SSH
mkdir -p ~/.ssh

# Copiar chave SSH que tem acesso aos servidores WooCommerce
# A chave precisa ter acesso ao servidor da Tarragona e Anac
cp /caminho/da/chave/id_ed25519 ~/.ssh/
chmod 600 ~/.ssh/id_ed25519
```

## 5. Deploy Inicial

```bash
chmod +x deploy.sh

# Deploy inicial (sem SSL)
./deploy.sh initial
```

## 6. Gerar Certificado SSL

```bash
# Aguardar DNS propagar (pode levar alguns minutos)
# Verificar: dig leads.posvendafacil.com.br

# Gerar certificado
./deploy.sh ssl
```

## 7. Criar Superusuario

```bash
./deploy.sh superuser
```

## 8. Migrar Dados (se necessario)

Se precisar migrar dados do ambiente de desenvolvimento:

```bash
# No ambiente de dev, exportar
pg_dump -U postgres customer_intelligence > backup.sql

# No servidor, importar
docker cp backup.sql customer_intelligence_db:/tmp/
docker compose exec db psql -U postgres customer_intelligence < /tmp/backup.sql
```

## Comandos Uteis

```bash
# Ver logs
./deploy.sh logs          # Web
./deploy.sh logs db       # Database
./deploy.sh logs nginx    # Nginx
./deploy.sh logs celery   # Celery worker

# Shell Django
./deploy.sh shell

# Backup
./deploy.sh backup

# Importar dados de empresa
./deploy.sh import tarragona 2024-01-01 2024-12-31
./deploy.sh import anacdeluxe 2024-01-01 2024-12-31

# Atualizar aplicacao
./deploy.sh update

# Reiniciar
./deploy.sh restart
```

## Estrutura de Diretorios

```
/opt/customer-intelligence/
├── docker-compose.yml
├── Dockerfile
├── .env.production
├── nginx/
│   ├── nginx.conf
│   └── sites/
│       └── leads.conf
├── certbot/
│   ├── conf/        # Certificados SSL
│   └── www/         # Desafio ACME
├── logs/            # Logs da aplicacao
├── backups/         # Backups do banco
└── media/           # Arquivos de upload
```

## Monitoramento

### Verificar status
```bash
docker compose ps
docker compose logs --tail=100 web
```

### Verificar saude
```bash
curl https://leads.posvendafacil.com.br/health/
```

### Renovar SSL (automatico)
O certbot renova automaticamente. Para forcar:
```bash
docker compose run --rm certbot renew --force-renewal
docker compose restart nginx
```

## Troubleshooting

### Erro de conexao com banco
```bash
docker compose logs db
docker compose exec db psql -U postgres -c "\l"
```

### Erro de permissao em arquivos estaticos
```bash
docker compose exec web python manage.py collectstatic --noinput --clear
```

### Erro de migracao
```bash
docker compose exec web python manage.py migrate --noinput
```

### Limpar tudo e recomecar
```bash
docker compose down -v  # Remove volumes!
./deploy.sh initial
```
