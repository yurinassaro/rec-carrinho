from django.urls import path
from . import views

urlpatterns = [
    path('authorize/<slug:empresa_slug>/', views.bling_authorize, name='bling_authorize'),
    path('callback/', views.bling_callback, name='bling_callback'),
]
