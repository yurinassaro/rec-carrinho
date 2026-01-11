from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .models import Empresa, EmpresaUsuario
from .forms import EmpresaConfigForm, WooCommerceConfigForm


@login_required
def select_empresa(request):
    """
    Pagina para usuario selecionar qual empresa acessar
    """
    empresas = EmpresaUsuario.objects.filter(
        usuario=request.user,
        empresa__ativo=True
    ).select_related('empresa').order_by('empresa__nome')

    if request.method == 'POST':
        empresa_id = request.POST.get('empresa_id')
        try:
            empresa_usuario = empresas.get(empresa_id=empresa_id)
            request.session['current_tenant_id'] = empresa_usuario.empresa.id
            messages.success(request, f'Acessando {empresa_usuario.empresa.nome}')
            return redirect('/admin/')
        except EmpresaUsuario.DoesNotExist:
            messages.error(request, 'Empresa invalida')

    # Se usuario tem apenas uma empresa, redirecionar automaticamente
    if empresas.count() == 1:
        empresa_usuario = empresas.first()
        request.session['current_tenant_id'] = empresa_usuario.empresa.id
        return redirect('/admin/')

    # Se usuario nao tem empresa
    if empresas.count() == 0:
        messages.error(request, 'Voce nao tem acesso a nenhuma empresa.')
        return redirect('/admin/logout/')

    return render(request, 'tenants/select_empresa.html', {
        'empresas': empresas
    })


@login_required
def switch_empresa(request, empresa_id):
    """
    Troca de empresa ativa
    """
    try:
        empresa_usuario = EmpresaUsuario.objects.get(
            usuario=request.user,
            empresa_id=empresa_id,
            empresa__ativo=True
        )
        request.session['current_tenant_id'] = empresa_usuario.empresa.id
        messages.success(request, f'Trocado para {empresa_usuario.empresa.nome}')
    except EmpresaUsuario.DoesNotExist:
        messages.error(request, 'Voce nao tem acesso a essa empresa')

    return redirect(request.META.get('HTTP_REFERER', '/admin/'))


@login_required
def current_empresa_api(request):
    """
    API para retornar empresa atual (para uso em JS)
    """
    tenant = getattr(request, 'tenant', None)
    if tenant:
        return JsonResponse({
            'id': tenant.id,
            'nome': tenant.nome,
            'slug': tenant.slug,
            'logo': tenant.logo.url if tenant.logo else None,
            'cor_primaria': tenant.cor_primaria,
        })
    return JsonResponse({'error': 'Nenhuma empresa selecionada'}, status=400)


@login_required
def list_empresas_api(request):
    """
    API para listar empresas do usuario
    """
    empresas = EmpresaUsuario.objects.filter(
        usuario=request.user,
        empresa__ativo=True
    ).select_related('empresa')

    current_tenant_id = request.session.get('current_tenant_id')

    data = []
    for eu in empresas:
        data.append({
            'id': eu.empresa.id,
            'nome': eu.empresa.nome,
            'slug': eu.empresa.slug,
            'role': eu.get_role_display(),
            'is_default': eu.is_default,
            'is_current': eu.empresa.id == current_tenant_id,
            'logo': eu.empresa.logo.url if eu.empresa.logo else None,
        })

    return JsonResponse({'empresas': data})


def _get_user_empresa_role(user, empresa):
    """Retorna o role do usuario na empresa"""
    try:
        eu = EmpresaUsuario.objects.get(usuario=user, empresa=empresa)
        return eu.role
    except EmpresaUsuario.DoesNotExist:
        return None


def _can_edit_config(user, empresa):
    """Verifica se usuario pode editar configuracoes da empresa"""
    if user.is_superuser:
        return True
    role = _get_user_empresa_role(user, empresa)
    return role in ['owner', 'admin']


@login_required
def configuracoes(request):
    """
    Painel de configuracoes da empresa atual
    """
    tenant = getattr(request, 'tenant', None)

    if not tenant:
        messages.error(request, 'Selecione uma empresa primeiro')
        return redirect('tenants:select')

    can_edit = _can_edit_config(request.user, tenant)
    role = _get_user_empresa_role(request.user, tenant)

    if request.method == 'POST' and can_edit:
        form_type = request.POST.get('form_type')

        if form_type == 'geral':
            form = EmpresaConfigForm(request.POST, request.FILES, instance=tenant)
            if form.is_valid():
                form.save()
                messages.success(request, 'Configuracoes gerais salvas!')
                return redirect('tenants:configuracoes')

        elif form_type == 'woocommerce':
            form = WooCommerceConfigForm(request.POST, instance=tenant)
            if form.is_valid():
                form.save()
                messages.success(request, 'Configuracoes WooCommerce salvas!')
                return redirect('tenants:configuracoes')

    # Forms para exibicao
    config_form = EmpresaConfigForm(instance=tenant)
    woo_form = WooCommerceConfigForm(instance=tenant)

    # Estatisticas da empresa
    stats = {
        'customers': tenant.customers.count(),
        'carts': tenant.carts.count(),
        'orders': tenant.orders.count(),
        'leads': tenant.leads.count(),
    }

    return render(request, 'tenants/configuracoes.html', {
        'empresa': tenant,
        'config_form': config_form,
        'woo_form': woo_form,
        'can_edit': can_edit,
        'role': role,
        'stats': stats,
    })


@login_required
@require_POST
def testar_conexao_woo(request):
    """
    Testa conexao com WooCommerce da empresa
    """
    tenant = getattr(request, 'tenant', None)

    if not tenant:
        return JsonResponse({'success': False, 'error': 'Nenhuma empresa selecionada'})

    if not _can_edit_config(request.user, tenant):
        return JsonResponse({'success': False, 'error': 'Sem permissao'})

    # Verificar se tem configuracoes
    if not tenant.woo_ssh_host or not tenant.woo_db_name:
        return JsonResponse({
            'success': False,
            'error': 'Configure os dados do WooCommerce primeiro'
        })

    try:
        import paramiko
        from sshtunnel import SSHTunnelForwarder
        import pymysql

        # Tentar conexao SSH
        ssh_key_path = tenant.woo_ssh_key_path or '~/.ssh/id_ed25519'
        ssh_key_path = ssh_key_path.replace('~', '/Users/Cliente')

        with SSHTunnelForwarder(
            (tenant.woo_ssh_host, 22),
            ssh_username=tenant.woo_ssh_user or 'root',
            ssh_pkey=ssh_key_path,
            remote_bind_address=(tenant.woo_db_host or '127.0.0.1', tenant.woo_db_port or 3306),
            local_bind_address=('127.0.0.1', 0)
        ) as tunnel:
            # Tentar conexao MySQL
            conn = pymysql.connect(
                host='127.0.0.1',
                port=tunnel.local_bind_port,
                user=tenant.woo_db_user,
                password=tenant.woo_db_password,
                database=tenant.woo_db_name,
                connect_timeout=10
            )

            cursor = conn.cursor()
            prefix = tenant.woo_table_prefix or 'wp_'
            cursor.execute(f"SELECT COUNT(*) FROM {prefix}posts WHERE post_type = 'shop_order'")
            orders_count = cursor.fetchone()[0]

            cursor.close()
            conn.close()

            return JsonResponse({
                'success': True,
                'message': f'Conexao OK! {orders_count} pedidos encontrados no WooCommerce.'
            })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })
