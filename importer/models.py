from django.db import models

# Create your models here.
class ImportDashboard(models.Model):
    """Modelo fake apenas para aparecer no admin"""

    class Meta:
        managed = False  # Não criar tabela no banco
        default_permissions = ()  # Sem permissões padrão
        verbose_name = '🚀 Dashboard de Importação'
        verbose_name_plural = '🚀 Dashboard de Importação'

class LeadsDashboard(models.Model):
    """Modelo proxy para criar link do dashboard de leads no admin"""

    class Meta:
        managed = False  # Não cria tabela no banco
        verbose_name = "📋 Dashboard de Importação de Leads"
        verbose_name_plural = "📋 Dashboard de Importação de Leads"
        app_label = 'importer'