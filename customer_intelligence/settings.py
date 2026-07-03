# customer_intelligence/settings.py

from pathlib import Path
from decouple import config
import os
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY', default='django-insecure-change-this-in-production')
DEBUG = config('DEBUG', default=True, cast=bool)

# Allowed hosts
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='*').split(',')

# CSRF trusted origins (para proxy reverso)
CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='').split(',')
CSRF_TRUSTED_ORIGINS = [x for x in CSRF_TRUSTED_ORIGINS if x]  # Remove vazios

INSTALLED_APPS = [
    # Admin interface (deve vir primeiro)
    'admin_interface',
    'colorfield',
    
    # Django apps
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Third party
    'rest_framework',
    'corsheaders',
    'django_extensions',
    'django_filters',
    'import_export',
    'django_celery_beat',
    'django_celery_results',
    
    # Local apps
    'tenants',
    'customers',
    'analytics',
    'importer',
    'marketing',
    'bling',
    'comunicacao',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Multi-tenant middleware
    'tenants.middleware.TenantMiddleware',
    'tenants.middleware.TenantRequiredMiddleware',
    'customers.middleware_crm.CRMButtonMiddleware',
]

ROOT_URLCONF = 'customer_intelligence.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'customer_intelligence.wsgi.application'

# Database PostgreSQL
# Suporta DATABASE_URL (Docker) ou variaveis individuais (dev)
DATABASE_URL = config('DATABASE_URL', default=None)

if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.parse(DATABASE_URL)
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': config('DB_NAME', default='customer_intelligence'),
            'USER': config('DB_USER', default='postgres'),
            'PASSWORD': config('DB_PASSWORD', default='postgres'),
            'HOST': config('DB_HOST', default='localhost'),
            'PORT': config('DB_PORT', default='5432'),
        }
    }

# Internationalization
LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# # Se estiver em desenvolvimento, adicione:
# STATICFILES_DIRS = [
#     BASE_DIR / 'static',
# ]

# W-API WhatsApp (w-api.app)
WAPI_URL = config('WAPI_URL', default='https://api.w-api.app/v1')
WAPI_TOKEN = config('WAPI_TOKEN', default='')
WAPI_INSTANCE = config('WAPI_INSTANCE', default='')

# Meta App Secret (para validação de signed_request no callback de exclusão de dados)
META_APP_SECRET = config('META_APP_SECRET', default='')

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# CORS
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = [
    'https://web.whatsapp.com',
    'https://leads.posvendafacil.com.br',
    'https://rw6asessoria.com.br',
    'https://www.rw6asessoria.com.br',
]
CORS_ALLOW_HEADERS = [
    'content-type',
    'x-api-key',
    'accept',
    'origin',
]

# Celery
CELERY_BROKER_URL = config('REDIS_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = config('REDIS_URL', default='redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

# Celery Beat schedule
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    'sync-bling-transito': {
        'task': 'bling.sync_pedidos_em_transito',
        'schedule': 30 * 60,  # a cada 30 minutos
    },
    'refresh-bling-tokens': {
        'task': 'bling.refresh_tokens',
        'schedule': 30 * 60,  # a cada 30 minutos
    },
    'import-ssh-diario': {
        'task': 'customers.import_ssh_diario',
        'schedule': crontab(hour=8, minute=30),  # todo dia as 8h30 (carrinhos + leads via SSH)
    },
    'sync-woocommerce-diario': {
        'task': 'customers.sync_woocommerce_diario',
        'schedule': crontab(hour=9, minute=0),  # todo dia as 9h (clientes + pedidos via API)
    },
    'enviar-promocoes-diarias': {
        'task': 'customers.enviar_promocoes_diarias',
        'schedule': crontab(hour=10, minute=0),  # todo dia as 10h
    },
    'cupom-diario-19h': {
        'task': 'customers.cupom_diario_19h',
        # 19h: importa carts+leads frescos, trata quem comprou, envia cupons
        # e manda relatorio no WhatsApp do admin (CUPOM_RELATORIO_WHATSAPP)
        'schedule': crontab(hour=19, minute=0),
    },
    'monitorar-wapi-08': {
        'task': 'customers.monitorar_wapi',
        'schedule': crontab(hour=8, minute=0),
    },
    'monitorar-wapi-14': {
        'task': 'customers.monitorar_wapi',
        'schedule': crontab(hour=14, minute=0),
    },
    'monitorar-wapi-20': {
        'task': 'customers.monitorar_wapi',
        'schedule': crontab(hour=20, minute=0),
    },
    # Motor de Réguas
    'processar-fila-envio': {
        'task': 'comunicacao.processar_fila_envio',
        'schedule': 2 * 60,  # a cada 2 minutos
    },
    'avaliar-regras-periodicas': {
        'task': 'comunicacao.avaliar_regras_periodicas',
        'schedule': crontab(minute=0),  # a cada hora cheia
    },
    'atualizar-stats-regras': {
        'task': 'comunicacao.atualizar_stats_regras',
        'schedule': crontab(hour=23, minute=0),  # todo dia as 23h
    },
}

# Cache - Usar Redis se REDIS_URL estiver disponível
REDIS_URL = config('REDIS_URL', default=None)
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "unique-dev",
        }
    }


# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
}

# Admin interface theme
X_FRAME_OPTIONS = 'SAMEORIGIN'

# Seguranca em producao
if not DEBUG:
    SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=True, cast=bool)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Whitenoise para arquivos estaticos
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': config('DJANGO_LOG_LEVEL', default='INFO'),
            'propagate': False,
        },
    },
}