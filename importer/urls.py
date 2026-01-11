from django.urls import path
from .views import (
    ImportDashboardView, ImportStatusView, check_recovery_view,
    leads_dashboard_view, leads_stats_view, import_leads_view,
    leads_import_status_view
)

app_name = 'importer'

urlpatterns = [
    path('', ImportDashboardView.as_view(), name='dashboard'),  # Rota principal
    path('dashboard/', ImportDashboardView.as_view(), name='dashboard_alt'),  # Rota alternativa
    path('import/', ImportDashboardView.as_view(), name='import_data'),
    path('status/', ImportStatusView.as_view(), name='import_status'),
    path('check-recovery/', check_recovery_view, name='check_recovery'),

    # Leads
    path('leads/', leads_dashboard_view, name='leads_dashboard'),  # Dashboard de Leads
    path('leads/stats/', leads_stats_view, name='leads_stats'),  # Estatísticas de Leads
    path('leads/import/', import_leads_view, name='import_leads'),  # Importar Leads
    path('leads/import/status/', leads_import_status_view, name='leads_import_status'),  # Status da Importação
]