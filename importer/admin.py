from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse
from django.http import HttpResponseRedirect
from .models import ImportDashboard, LeadsDashboard

@admin.register(ImportDashboard)
class ImportDashboardAdmin(admin.ModelAdmin):
    """Admin para redirecionar ao dashboard"""

    def changelist_view(self, request, extra_context=None):
        # Redireciona para a página de importação
        return HttpResponseRedirect(reverse('importer:dashboard'))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return True  # Precisa ser True para aparecer no menu

    def has_delete_permission(self, request, obj=None):
        return False

    def has_module_permission(self, request):
        return True

@admin.register(LeadsDashboard)
class LeadsDashboardAdmin(admin.ModelAdmin):
    """Admin para redirecionar ao dashboard de leads"""

    def changelist_view(self, request, extra_context=None):
        # Redireciona para a página de importação de leads
        return HttpResponseRedirect(reverse('importer:leads_dashboard'))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return True  # Precisa ser True para aparecer no menu

    def has_delete_permission(self, request, obj=None):
        return False

    def has_module_permission(self, request):
        return True