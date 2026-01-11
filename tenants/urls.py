from django.urls import path
from . import views

app_name = 'tenants'

urlpatterns = [
    path('select/', views.select_empresa, name='select'),
    path('switch/<int:empresa_id>/', views.switch_empresa, name='switch'),
    path('configuracoes/', views.configuracoes, name='configuracoes'),
    path('api/current/', views.current_empresa_api, name='api_current'),
    path('api/list/', views.list_empresas_api, name='api_list'),
    path('api/testar-conexao/', views.testar_conexao_woo, name='testar_conexao'),
]
