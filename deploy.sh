#!/bin/bash
# ===========================================
# Script de Deploy - Customer Intelligence
# ===========================================

set -e

echo "=========================================="
echo "  Customer Intelligence - Deploy Script"
echo "=========================================="

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Verificar se .env.production existe
if [ ! -f .env.production ]; then
    echo -e "${RED}Erro: .env.production nao encontrado!${NC}"
    echo "Copie .env.production.example para .env.production e configure"
    exit 1
fi

# Carregar variaveis
source .env.production

# Criar diretorios necessarios
echo -e "${YELLOW}Criando diretorios...${NC}"
mkdir -p nginx/sites logs certbot/conf certbot/www media

# Funcao para deploy inicial (sem SSL)
deploy_initial() {
    echo -e "${YELLOW}Deploy inicial (sem SSL)...${NC}"

    # Usar config sem SSL
    cp nginx/sites/leads-initial.conf nginx/sites/leads.conf.bak 2>/dev/null || true
    cp nginx/sites/leads-initial.conf nginx/sites/active.conf

    # Build e start
    docker compose build
    docker compose up -d db redis

    echo "Aguardando banco de dados..."
    sleep 10

    docker compose up -d web nginx

    echo -e "${GREEN}Deploy inicial concluido!${NC}"
    echo ""
    echo "Proximo passo: gerar certificado SSL"
    echo "Execute: ./deploy.sh ssl"
}

# Funcao para gerar SSL
generate_ssl() {
    echo -e "${YELLOW}Gerando certificado SSL...${NC}"

    # Verificar se dominio resolve
    echo "Verificando DNS..."
    if ! host leads.posvendafacil.com.br > /dev/null 2>&1; then
        echo -e "${RED}Erro: DNS nao configurado para leads.posvendafacil.com.br${NC}"
        echo "Configure o DNS antes de gerar o certificado"
        exit 1
    fi

    # Gerar certificado
    docker compose run --rm certbot certonly \
        --webroot \
        --webroot-path=/var/www/certbot \
        --email admin@posvendafacil.com.br \
        --agree-tos \
        --no-eff-email \
        -d leads.posvendafacil.com.br

    # Ativar config com SSL
    cp nginx/sites/leads.conf nginx/sites/active.conf

    # Reiniciar nginx
    docker compose restart nginx

    echo -e "${GREEN}SSL configurado com sucesso!${NC}"
}

# Funcao para update
update() {
    echo -e "${YELLOW}Atualizando aplicacao...${NC}"

    # Pull latest code
    git pull origin main 2>/dev/null || true

    # Rebuild e restart
    docker compose build web celery celery-beat
    docker compose up -d

    # Migrations
    docker compose exec web python manage.py migrate --noinput

    # Collectstatic
    docker compose exec web python manage.py collectstatic --noinput --clear

    echo -e "${GREEN}Update concluido!${NC}"
}

# Funcao para logs
logs() {
    docker compose logs -f ${1:-web}
}

# Funcao para shell
shell() {
    docker compose exec web python manage.py shell
}

# Funcao para criar superuser
createsuperuser() {
    docker compose exec web python manage.py createsuperuser
}

# Funcao para backup
backup() {
    echo -e "${YELLOW}Criando backup...${NC}"
    BACKUP_FILE="backup_$(date +%Y%m%d_%H%M%S).sql"
    docker compose exec db pg_dump -U postgres customer_intelligence > "backups/${BACKUP_FILE}"
    echo -e "${GREEN}Backup criado: backups/${BACKUP_FILE}${NC}"
}

# Funcao para importar dados
import_data() {
    EMPRESA=${1:-tarragona}
    START_DATE=${2:-$(date -d '7 days ago' +%Y-%m-%d)}
    END_DATE=${3:-$(date +%Y-%m-%d)}

    echo -e "${YELLOW}Importando dados para ${EMPRESA}...${NC}"
    docker compose exec web python manage.py import_customers \
        --empresa=${EMPRESA} \
        --start_date=${START_DATE} \
        --end_date=${END_DATE} \
        --import_type=all
}

# Menu de ajuda
show_help() {
    echo "Uso: ./deploy.sh [comando]"
    echo ""
    echo "Comandos:"
    echo "  initial     - Deploy inicial (sem SSL)"
    echo "  ssl         - Gerar certificado SSL"
    echo "  update      - Atualizar aplicacao"
    echo "  logs [svc]  - Ver logs (web, db, nginx, celery)"
    echo "  shell       - Abrir Django shell"
    echo "  superuser   - Criar superusuario"
    echo "  backup      - Criar backup do banco"
    echo "  import [empresa] [start] [end] - Importar dados"
    echo "  stop        - Parar todos os containers"
    echo "  restart     - Reiniciar todos os containers"
    echo ""
}

# Processar comando
case "${1:-help}" in
    initial)
        deploy_initial
        ;;
    ssl)
        generate_ssl
        ;;
    update)
        update
        ;;
    logs)
        logs $2
        ;;
    shell)
        shell
        ;;
    superuser)
        createsuperuser
        ;;
    backup)
        mkdir -p backups
        backup
        ;;
    import)
        import_data $2 $3 $4
        ;;
    stop)
        docker compose down
        ;;
    restart)
        docker compose restart
        ;;
    *)
        show_help
        ;;
esac
