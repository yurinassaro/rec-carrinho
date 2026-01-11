# Makefile - Customer Intelligence
# Comandos para desenvolvimento e deploy

.PHONY: help dev prod logs shell migrate import backup

help:
	@echo "Comandos disponiveis:"
	@echo "  make dev        - Rodar em desenvolvimento local"
	@echo "  make prod       - Subir em producao (docker)"
	@echo "  make prod-down  - Parar producao"
	@echo "  make prod-logs  - Ver logs de producao"
	@echo "  make shell      - Django shell (producao)"
	@echo "  make migrate    - Rodar migrations (producao)"
	@echo "  make import     - Importar dados (producao)"
	@echo "  make backup     - Backup do banco (producao)"
	@echo "  make build      - Rebuild das imagens"

# Desenvolvimento local
dev:
	python manage.py runserver 0.0.0.0:9000

# Producao
prod:
	docker-compose -f docker-compose.prod.yml up -d

prod-down:
	docker-compose -f docker-compose.prod.yml down

prod-logs:
	docker-compose -f docker-compose.prod.yml logs -f

prod-logs-web:
	docker-compose -f docker-compose.prod.yml logs -f web

# Build
build:
	docker-compose -f docker-compose.prod.yml build

build-no-cache:
	docker-compose -f docker-compose.prod.yml build --no-cache

# Shell
shell:
	docker-compose -f docker-compose.prod.yml exec web python manage.py shell

# Migrations
migrate:
	docker-compose -f docker-compose.prod.yml exec web python manage.py migrate

makemigrations:
	docker-compose -f docker-compose.prod.yml exec web python manage.py makemigrations

# Static files
collectstatic:
	docker-compose -f docker-compose.prod.yml exec web python manage.py collectstatic --noinput

# Superuser
superuser:
	docker-compose -f docker-compose.prod.yml exec web python manage.py createsuperuser

# Import dados
import-tarragona:
	docker-compose -f docker-compose.prod.yml exec web python manage.py import_customers --empresa=tarragona --import_type=all

import-anac:
	docker-compose -f docker-compose.prod.yml exec web python manage.py import_customers --empresa=anacdeluxe --import_type=all

# Backup
backup:
	@mkdir -p backups
	@docker-compose -f docker-compose.prod.yml exec -T db pg_dump -U leads customer_intelligence > backups/backup_$$(date +%Y%m%d_%H%M%S).sql
	@echo "Backup criado em backups/"

# Restore (uso: make restore FILE=backups/backup_xxx.sql)
restore:
	@docker-compose -f docker-compose.prod.yml exec -T db psql -U leads customer_intelligence < $(FILE)

# Limpar tudo (CUIDADO!)
clean:
	docker-compose -f docker-compose.prod.yml down -v
	docker system prune -f
