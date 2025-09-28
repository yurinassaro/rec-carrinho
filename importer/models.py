from django.db import models

# Create your models here.\
class ImportDashboard(models.Model):
    """Modelo fake apenas para aparecer no admin"""
    
    class Meta:
        managed = False  # Não criar tabela no banco
        default_permissions = ()  # Sem permissões padrão
        verbose_name = '🚀 Dashboard de Importação'
        verbose_name_plural = '🚀 Dashboard de Importação'