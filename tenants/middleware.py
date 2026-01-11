import threading
from django.shortcuts import redirect
from django.contrib import messages

# Thread-local storage para o tenant atual
_thread_locals = threading.local()


def get_current_tenant():
    """Retorna o tenant atual do contexto"""
    return getattr(_thread_locals, 'tenant', None)


def set_current_tenant(tenant):
    """Define o tenant atual no contexto"""
    _thread_locals.tenant = tenant


class TenantMiddleware:
    """
    Middleware para detectar empresa baseado na sessao do usuario.

    Fluxo:
    1. Usuario faz login
    2. Se tem mais de uma empresa -> escolhe qual acessar
    3. Se tem apenas uma -> acessa automaticamente
    4. Superuser acessa tudo
    """

    # URLs que nao precisam de empresa
    EXEMPT_PATHS = [
        '/admin/login/',
        '/admin/logout/',
        '/api/auth/',
        '/health/',
        '/static/',
        '/media/',
        '/tenants/select/',
        '/tenants/switch/',
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Resetar tenant
        set_current_tenant(None)
        request.tenant = None

        # Verificar se URL e isenta
        path = request.path
        if any(path.startswith(exempt) for exempt in self.EXEMPT_PATHS):
            return self.get_response(request)

        # Detectar tenant pela sessao
        tenant = self._get_tenant_from_session(request)

        if tenant:
            set_current_tenant(tenant)
            request.tenant = tenant

        response = self.get_response(request)
        return response

    def _get_tenant_from_session(self, request):
        """
        Detecta empresa pela sessao do usuario logado
        """
        from tenants.models import Empresa, EmpresaUsuario

        if not request.user.is_authenticated:
            return None

        # Superuser pode nao ter empresa selecionada
        # mas ainda assim queremos tentar carregar uma se estiver na sessao

        # Verificar sessao
        tenant_id = request.session.get('current_tenant_id')
        if tenant_id:
            try:
                # Superuser pode acessar qualquer empresa
                if request.user.is_superuser:
                    return Empresa.objects.get(id=tenant_id, ativo=True)

                # Usuario normal precisa ter acesso
                empresa_usuario = EmpresaUsuario.objects.select_related('empresa').get(
                    empresa_id=tenant_id,
                    usuario=request.user,
                    empresa__ativo=True
                )
                return empresa_usuario.empresa
            except (Empresa.DoesNotExist, EmpresaUsuario.DoesNotExist):
                # Remover tenant invalido da sessao
                if 'current_tenant_id' in request.session:
                    del request.session['current_tenant_id']

        # Superuser sem empresa selecionada - nao forcar
        if request.user.is_superuser:
            return None

        # Tentar empresa padrao do usuario
        try:
            empresa_usuario = EmpresaUsuario.objects.select_related('empresa').get(
                usuario=request.user,
                is_default=True,
                empresa__ativo=True
            )
            request.session['current_tenant_id'] = empresa_usuario.empresa.id
            return empresa_usuario.empresa
        except EmpresaUsuario.DoesNotExist:
            pass

        # Pegar primeira empresa do usuario
        empresa_usuario = EmpresaUsuario.objects.select_related('empresa').filter(
            usuario=request.user,
            empresa__ativo=True
        ).first()

        if empresa_usuario:
            request.session['current_tenant_id'] = empresa_usuario.empresa.id
            return empresa_usuario.empresa

        return None


class TenantRequiredMiddleware:
    """
    Middleware que redireciona para selecao de empresa se necessario.
    Deve vir DEPOIS do TenantMiddleware.
    """

    # URLs que nao precisam de empresa
    EXEMPT_PATHS = [
        '/admin/login/',
        '/admin/logout/',
        '/static/',
        '/media/',
        '/tenants/select/',
        '/tenants/switch/',
        '/tenants/',  # APIs do tenant
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path

        # URLs isentas
        if any(path.startswith(exempt) for exempt in self.EXEMPT_PATHS):
            return self.get_response(request)

        # Superuser nao precisa de empresa para acessar o admin
        if request.user.is_authenticated and request.user.is_superuser:
            return self.get_response(request)

        # Se usuario logado sem empresa, redirecionar para selecao
        if request.user.is_authenticated and not request.tenant:
            from tenants.models import EmpresaUsuario

            # Verificar se usuario tem alguma empresa
            empresas_count = EmpresaUsuario.objects.filter(
                usuario=request.user,
                empresa__ativo=True
            ).count()

            if empresas_count == 0:
                messages.error(request, 'Voce nao tem acesso a nenhuma empresa. Contate o administrador.')
                return redirect('/admin/logout/')
            else:
                # Redirecionar para selecao
                return redirect('/tenants/select/')

        return self.get_response(request)
