from django.urls import path
from . import views_crm

app_name = 'crm'

urlpatterns = [
    path('', views_crm.crm_kanban, name='kanban'),
    path('api/mover/', views_crm.crm_mover_contato, name='mover_contato'),
    path('api/contato/criar/', views_crm.crm_criar_contato, name='criar_contato'),
    path('api/contato/editar/', views_crm.crm_editar_contato, name='editar_contato'),
    path('api/contato/deletar/', views_crm.crm_deletar_contato, name='deletar_contato'),
    path('api/contato/<int:contato_id>/', views_crm.crm_contato_detalhe, name='contato_detalhe'),
    path('api/pipeline/criar/', views_crm.crm_criar_pipeline, name='criar_pipeline'),
]
