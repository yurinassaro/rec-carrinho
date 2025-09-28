from django.urls import path
from .views import ImportDashboardView, ImportStatusView

app_name = 'importer'

urlpatterns = [
    path('', ImportDashboardView.as_view(), name='dashboard'),  # Rota principal
    path('dashboard/', ImportDashboardView.as_view(), name='dashboard_alt'),  # Rota alternativa
    path('import/', ImportDashboardView.as_view(), name='import_data'),
    path('status/', ImportStatusView.as_view(), name='import_status'),
]