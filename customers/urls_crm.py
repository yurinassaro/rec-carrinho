from django.urls import path
from . import views_crm, views_inbox, views_bling_retirada

app_name = 'crm'

urlpatterns = [
    path('', views_crm.crm_kanban, name='kanban'),
    path('retirada/', views_bling_retirada.aguardando_retirada, name='aguardando_retirada'),
    path('retirada/enviar/', views_bling_retirada.aguardando_retirada_enviar, name='aguardando_retirada_enviar'),
    path('inbox/', views_inbox.inbox_view, name='inbox'),
    path('inbox/enviar/', views_inbox.inbox_enviar, name='inbox_enviar'),
    path('inbox/midia/<int:msg_id>/', views_inbox.inbox_midia, name='inbox_midia'),
    path('inbox/api/conversas/', views_inbox.inbox_conversas_api, name='inbox_conversas_api'),
    path('inbox/api/mensagens/', views_inbox.inbox_mensagens_api, name='inbox_mensagens_api'),
    path('api/mover/', views_crm.crm_mover_contato, name='mover_contato'),
    path('api/contato/criar/', views_crm.crm_criar_contato, name='criar_contato'),
    path('api/contato/editar/', views_crm.crm_editar_contato, name='editar_contato'),
    path('api/contato/deletar/', views_crm.crm_deletar_contato, name='deletar_contato'),
    path('api/contato/<int:contato_id>/', views_crm.crm_contato_detalhe, name='contato_detalhe'),
    path('api/pipeline/criar/', views_crm.crm_criar_pipeline, name='criar_pipeline'),
    path('api/pipeline/editar/', views_crm.crm_editar_pipeline, name='editar_pipeline'),
    path('api/pipeline/deletar/', views_crm.crm_deletar_pipeline, name='deletar_pipeline'),
    path('api/pipeline/<int:pipeline_id>/', views_crm.crm_pipeline_detalhe, name='pipeline_detalhe'),
]
