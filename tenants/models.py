from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify


class InstanciaWAPI(models.Model):
    """
    Instância W-API vinculada a uma empresa.
    Permite múltiplas instâncias (ex: Pós-Venda, Vendas, Suporte).
    """
    empresa = models.ForeignKey(
        'Empresa',
        on_delete=models.CASCADE,
        related_name='instancias_wapi'
    )
    nome = models.CharField(
        max_length=100,
        help_text='Ex: Pós-Venda, Vendas, Suporte'
    )
    wapi_token = models.CharField(max_length=200, verbose_name='Token')
    wapi_instance = models.CharField(max_length=200, verbose_name='Instância')
    ativo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'instancias_wapi'
        verbose_name = 'Instância W-API'
        verbose_name_plural = 'Instâncias W-API'
        ordering = ['nome']

    def __str__(self):
        return f"{self.nome} ({self.empresa.nome})"


class Empresa(models.Model):
    """
    Tenant principal - representa cada empresa/loja
    """
    # Identificacao
    nome = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100, unique=True, db_index=True)
    dominio = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text='Subdominio (ex: anacdeluxe para anacdeluxe.posvendafacil.com.br)'
    )

    # Status
    ativo = models.BooleanField(default=True)
    plano = models.CharField(max_length=50, choices=[
        ('basic', 'Basico'),
        ('pro', 'Profissional'),
        ('enterprise', 'Enterprise'),
    ], default='basic')

    # Módulos liberados no painel (front lê via /api/me/). Chaves genéricas
    # (ex: 'instagram', 'whatsapp_mapeamento', 'whatsapp_ia') OU exclusivas de
    # cliente (ex: 'tarragona_x', 'neuraxo_y'). O servidor manda; o front só mostra.
    modulos = models.JSONField(
        default=list, blank=True,
        verbose_name='Módulos liberados',
        help_text="Lista de chaves de módulo, ex: ['instagram','whatsapp_mapeamento']",
    )

    # Assinatura / pagamento (Asaas)
    assinatura_ativa = models.BooleanField(
        default=False,
        verbose_name='Assinatura ativa',
        help_text='Ligado quando o pagamento é confirmado (webhook Asaas).',
    )
    asaas_customer_id = models.CharField(max_length=64, blank=True, default='', db_index=True)
    asaas_subscription_id = models.CharField(max_length=64, blank=True, default='')
    assinatura_expira = models.DateTimeField(null=True, blank=True)

    # Credenciais WooCommerce - SSH
    woo_ssh_host = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='SSH Host',
        help_text='IP ou hostname do servidor (ex: 157.245.119.130)'
    )
    woo_ssh_port = models.IntegerField(
        default=22,
        verbose_name='SSH Port'
    )
    woo_ssh_user = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='SSH Usuario',
        help_text='Usuario SSH (ex: root)'
    )
    woo_ssh_key_path = models.CharField(
        max_length=500,
        blank=True,
        verbose_name='SSH Key Path',
        help_text='Caminho da chave SSH (ex: ~/.ssh/id_ed25519)'
    )

    # Credenciais WooCommerce - Database
    woo_db_host = models.CharField(
        max_length=200,
        default='127.0.0.1',
        verbose_name='DB Host'
    )
    woo_db_port = models.IntegerField(
        default=3306,
        verbose_name='DB Port'
    )
    woo_db_name = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='DB Nome'
    )
    woo_db_user = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='DB Usuario'
    )
    woo_db_password = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='DB Senha'
    )
    woo_table_prefix = models.CharField(
        max_length=20,
        default='wp_',
        verbose_name='Table Prefix',
        help_text='Prefixo das tabelas WordPress (ex: wp_)'
    )

    # WooCommerce REST API
    woo_store_url = models.URLField(
        max_length=300,
        blank=True,
        verbose_name='URL da Loja',
        help_text='URL do WooCommerce (ex: https://tarragona.com.br)'
    )
    woo_consumer_key = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='Consumer Key',
        help_text='Consumer Key da API REST WooCommerce (WooCommerce > Settings > Advanced > REST API)'
    )
    woo_consumer_secret = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='Consumer Secret',
        help_text='Consumer Secret da API REST WooCommerce'
    )

    # Webhook WooCommerce
    woo_webhook_secret = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='Webhook Secret',
        help_text='Secret do webhook WooCommerce (configurar no WooCommerce > Settings > Advanced > Webhooks)'
    )

    # Configuracao Form Vibes - Mapeamento de campos
    fv_field_nome = models.CharField(
        max_length=100,
        default='Nome_3',
        verbose_name='Campo Nome',
        help_text='Nome do meta_key para o campo Nome (ex: Nome_3, Nome)'
    )
    fv_field_whatsapp = models.CharField(
        max_length=100,
        default='Whatsapp_8',
        verbose_name='Campo WhatsApp',
        help_text='Nome do meta_key para WhatsApp (ex: Whatsapp_8, Whatsapp - DDD + Numero)'
    )
    fv_field_tamanho = models.CharField(
        max_length=100,
        default='Número_do_sapato_9',
        blank=True,
        verbose_name='Campo Tamanho/Sapato',
        help_text='Nome do meta_key para tamanho (ex: Número_do_sapato_9). Deixe vazio se não usar.'
    )

    # W-API WhatsApp (w-api.app) - pode sobrescrever por empresa
    wapi_token = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='W-API Token',
        help_text='Token da W-API. Deixe vazio para usar o padrão do sistema.'
    )
    wapi_instance = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='W-API Instância',
        help_text='ID da instância W-API. Deixe vazio para usar o padrão do sistema.'
    )
    neuraxo_agent_key = models.CharField(
        max_length=80,
        blank=True,
        default='',
        verbose_name='Chave do Agente (neuraxo-agent)',
        help_text='X-Api-Key do agente desta empresa no neuraxo-agent. Se preenchida '
                  '(e NEURAXO_AGENT_URL setada), o Copiloto usa o agente em vez do Claude.'
    )
    wapi_ativo = models.BooleanField(
        default=True,
        verbose_name='WhatsApp Ativo',
        help_text='Ativar/desativar envio automático de WhatsApp'
    )
    wapi_telefone_monitoramento = models.CharField(
        max_length=20,
        blank=True,
        verbose_name='Telefone Monitoramento',
        help_text='Numero para receber alertas de status da W-API (ex: 5516999999999). 3x ao dia: 08h, 14h, 20h.'
    )

    # Ativo/inativo por tipo de mensagem
    msg_ativa_lead = models.BooleanField(default=True, verbose_name='Ativo')
    msg_ativa_lead_cliente = models.BooleanField(default=True, verbose_name='Ativo')
    msg_ativa_cart = models.BooleanField(default=True, verbose_name='Ativo')
    msg_ativa_pedido_novo = models.BooleanField(default=True, verbose_name='Ativo')
    msg_ativa_pedido_processando = models.BooleanField(default=True, verbose_name='Ativo')
    msg_ativa_pedido_embalado = models.BooleanField(default=True, verbose_name='Ativo')
    msg_ativa_pedido_transito = models.BooleanField(default=True, verbose_name='Ativo')
    msg_ativa_pedido_concluido = models.BooleanField(default=True, verbose_name='Ativo')
    msg_ativa_pedido_cancelado = models.BooleanField(default=True, verbose_name='Ativo')

    # Mensagens WhatsApp personalizadas
    msg_whatsapp_lead = models.TextField(
        default='Olá {nome}, tudo bem ??',
        verbose_name='Mensagem WhatsApp - Lead Novo',
        help_text='Mensagem para leads novos (prospects). Use {nome}.'
    )
    msg_whatsapp_lead_cliente = models.TextField(
        default='Olá {nome}, que bom ter você de volta! Vimos que você já comprou conosco e temos novidades especiais pra você. Posso te ajudar?',
        verbose_name='Mensagem WhatsApp - Lead já Cliente',
        help_text='Mensagem para leads que já são clientes. Use {nome}.'
    )
    msg_whatsapp_cart = models.TextField(
        default='Olá {nome}, tudo bem ??',
        verbose_name='Mensagem WhatsApp - Carrinho',
        help_text='Mensagem para recuperação de carrinho. Use {nome}.'
    )
    msg_whatsapp_pedido_novo = models.TextField(
        default='Olá {nome}! Recebemos seu pedido #{numero}. Obrigado pela compra! Em breve você receberá atualizações sobre o envio.',
        verbose_name='Mensagem WhatsApp - Pedido Novo',
        help_text='Mensagem quando cliente faz uma compra. Use {nome}, {numero}, {valor}.'
    )
    msg_whatsapp_pedido_embalado = models.TextField(
        default='Olá {nome}! Seu pedido #{numero} já foi embalado e saiu da fábrica! O código de rastreio será enviado para o seu email ainda hoje à noite.',
        verbose_name='Mensagem WhatsApp - Pedido Embalado',
        help_text='Mensagem quando pedido é embalado. Use {nome}, {numero}.'
    )
    msg_whatsapp_pedido_processando = models.TextField(
        default='Olá {nome}! Seu pagamento do pedido #{numero} foi confirmado! Estamos preparando seu pedido.',
        verbose_name='Mensagem WhatsApp - Pedido Processando',
        help_text='Mensagem quando pagamento é confirmado. Use {nome}, {numero}, {valor}.'
    )
    msg_whatsapp_pedido_transito = models.TextField(
        default='Olá {nome}! Seu pedido #{numero} está em trânsito! Acompanhe pelo código de rastreio no seu email.',
        verbose_name='Mensagem WhatsApp - Pedido em Trânsito',
        help_text='Mensagem quando pedido está em trânsito. Use {nome}, {numero}, {valor}.'
    )
    msg_whatsapp_pedido_concluido = models.TextField(
        default='Olá {nome}! Seu pedido #{numero} foi entregue! Esperamos que goste. Qualquer dúvida estamos à disposição.',
        verbose_name='Mensagem WhatsApp - Pedido Concluído',
        help_text='Mensagem quando pedido é entregue. Use {nome}, {numero}, {valor}.'
    )
    msg_whatsapp_pedido_cancelado = models.TextField(
        default='Olá {nome}, seu pedido #{numero} foi cancelado. Se precisar de ajuda, estamos à disposição.',
        verbose_name='Mensagem WhatsApp - Pedido Cancelado',
        help_text='Mensagem quando pedido é cancelado. Use {nome}, {numero}, {valor}.'
    )

    # Instâncias W-API por tipo de mensagem (fallback: wapi_token/wapi_instance acima)
    instancia_lead = models.ForeignKey(
        InstanciaWAPI, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='Instância - Lead Novo',
    )
    instancia_lead_cliente = models.ForeignKey(
        InstanciaWAPI, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='Instância - Lead Cliente',
    )
    instancia_cart = models.ForeignKey(
        InstanciaWAPI, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='Instância - Carrinho',
    )
    instancia_pedido_novo = models.ForeignKey(
        InstanciaWAPI, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='Instância - Pedido Novo',
    )
    instancia_pedido_processando = models.ForeignKey(
        InstanciaWAPI, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='Instância - Pedido Processando',
    )
    instancia_pedido_embalado = models.ForeignKey(
        InstanciaWAPI, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='Instância - Pedido Embalado',
    )
    instancia_pedido_transito = models.ForeignKey(
        InstanciaWAPI, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='Instância - Pedido em Trânsito',
    )
    instancia_pedido_concluido = models.ForeignKey(
        InstanciaWAPI, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='Instância - Pedido Concluído',
    )
    instancia_pedido_cancelado = models.ForeignKey(
        InstanciaWAPI, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='Instância - Pedido Cancelado',
    )

    # Bling API V3
    bling_client_id = models.CharField(
        max_length=200, blank=True, verbose_name='Bling Client ID',
        help_text='Client ID do app Bling (API V3)'
    )
    bling_client_secret = models.CharField(
        max_length=200, blank=True, verbose_name='Bling Client Secret',
        help_text='Client Secret do app Bling (API V3)'
    )
    bling_situacao_processando_id = models.CharField(
        max_length=50, blank=True, verbose_name='ID Situação Processando',
        help_text='ID da situação "Processando" no Bling (varia por conta)'
    )
    bling_situacao_embalado_id = models.CharField(
        max_length=50, blank=True, verbose_name='ID Situação Embalado',
        help_text='ID da situação "Embalado" no Bling (varia por conta)'
    )
    bling_situacao_transito_id = models.CharField(
        max_length=50, blank=True, verbose_name='ID Situação Em Trânsito',
        help_text='ID da situação "Em Trânsito" no Bling (varia por conta)'
    )
    bling_situacao_concluido_id = models.CharField(
        max_length=50, blank=True, verbose_name='ID Situação Concluído',
        help_text='ID da situação "Concluído" no Bling (varia por conta)'
    )
    bling_situacao_cancelado_id = models.CharField(
        max_length=50, blank=True, verbose_name='ID Situação Cancelado',
        help_text='ID da situação "Cancelado" no Bling (varia por conta)'
    )
    bling_logistica_id = models.CharField(
        max_length=50, blank=True, verbose_name='ID Logística (Objetos de postagem)',
        help_text='ID da logística no Bling para listar objetos "Aguardando retirada" '
                  '(veja na URL integracoes_logisticas.php?logisticId=...)'
    )
    msg_whatsapp_aguardando_retirada = models.TextField(
        blank=True,
        verbose_name='Mensagem Aguardando Retirada',
        help_text='Variáveis: {nome}, {pedido}, {codigo}, {link}',
        default=(
            'Olá {nome}! 📦 Seu pedido #{pedido} já chegou e está *disponível para '
            'retirada* na agência dos Correios.\n\n'
            'Código de rastreio: *{codigo}*\n'
            'Acompanhe aqui: {link}\n\n'
            'Não esqueça de levar um documento com foto. 😊'
        ),
    )

    # Meta WhatsApp Business API (Cloud API)
    meta_waba_id = models.CharField(
        max_length=100, blank=True, verbose_name='WABA ID',
        help_text='WhatsApp Business Account ID'
    )
    meta_phone_number_id = models.CharField(
        max_length=100, blank=True, verbose_name='Phone Number ID',
        help_text='ID do número de telefone no Meta Business'
    )
    meta_access_token = models.TextField(
        blank=True, verbose_name='Access Token Meta',
        help_text='Token de acesso permanente da Meta Cloud API'
    )
    meta_template_transito = models.CharField(
        max_length=100, default='pedido_em_transito', blank=True,
        verbose_name='Template Em Transito',
        help_text='Nome do template aprovado no WhatsApp Manager'
    )
    meta_template_pedido_cadastro = models.CharField(
        max_length=100, default='cadastro_pedido', blank=True,
        verbose_name='Template Cadastro Pedido',
        help_text='Template enviado quando pedido e criado no site. Params: {{1}}=nome, {{2}}=numero do pedido'
    )
    meta_webhook_verify_token = models.CharField(
        max_length=100, blank=True,
        verbose_name='Webhook Verify Token',
        help_text='Token para verificacao do webhook Meta (voce define, coloca o mesmo no Meta Business)'
    )
    meta_whatsapp_humano = models.CharField(
        max_length=20, blank=True,
        verbose_name='WhatsApp Humano (atendimento)',
        help_text='Numero do atendente humano para encaminhar respostas (ex: 5516999999999)'
    )
    whatsapp_atendimento_oficial = models.CharField(
        max_length=30, blank=True,
        verbose_name='WhatsApp Oficial de Atendimento',
        help_text=(
            'Numero OFICIAL de atendimento ao cliente (onde ele deve chamar). '
            'O numero que envia os avisos automaticos NAO atende. '
            'Ex: (16) 99999-9999'
        )
    )
    meta_resposta_automatica = models.TextField(
        blank=True,
        default=(
            'Olá {nome}! Recebemos sua mensagem 🙏\n\n'
            'ℹ️ Este número é apenas de *avisos automáticos* e não realiza '
            'atendimento.\n\n'
            '📦 Para consultar o status do seu pedido, acesse:\n'
            '{consulta}\n\n'
            '⏱️ Se o seu pedido ainda não aparecer lá, aguarde até 24 horas — '
            'ele será sincronizado no sistema de consulta.\n\n'
            '📞 Para falar com um atendente, chame em nosso número oficial de '
            'atendimento: {atendimento_oficial}'
        ),
        verbose_name='Resposta Automatica (cliente responde)',
        help_text=(
            'Texto enviado automaticamente quando cliente responde uma mensagem do bot. '
            'Deixe em branco para nao enviar. Variaveis: '
            '{consulta} = link de consulta de pedido, {nome} = nome do cliente, '
            '{atendimento_oficial} = numero oficial de atendimento, '
            '{whatsapp_humano} = numero do atendente (encaminhamento interno).'
        )
    )
    meta_template_lead_cliente = models.CharField(
        max_length=100, default='promocoes_tarragona_leads_clientes', blank=True,
        verbose_name='Template Lead Cliente',
        help_text='Template para leads que ja sao clientes. Params: {{1}}=nome, {{2}}=cupom, {{3}}=desconto, {{4}}=validade'
    )
    meta_template_lead_nao_cliente = models.CharField(
        max_length=100, default='promocoes_tarragona_leads_nao_clientes', blank=True,
        verbose_name='Template Lead Nao Cliente',
        help_text='Template para leads que nunca compraram. Params: {{1}}=nome, {{2}}=cupom, {{3}}=desconto, {{4}}=validade'
    )
    meta_template_cart = models.CharField(
        max_length=100, default='carrinho_abandonado_sem_cupom', blank=True,
        verbose_name='Template Carrinho Abandonado',
        help_text='Template para recuperacao de carrinho. Body: {{1}}=nome. Botao URL dinamica: session_id do carrinho (wcf_ac_token)'
    )

    meta_template_lead_nao_cliente_cupom = models.CharField(
        max_length=100, default='cupom_tarragona_leads_nao_clientes', blank=True,
        verbose_name='Template Lead Nao Cliente (com cupom)',
        help_text='Template com cupom para leads que nunca compraram (primeira compra). Params: {{1}}=nome, {{2}}=cupom, {{3}}=desconto, {{4}}=validade'
    )
    meta_template_cliente_inativo = models.CharField(
        max_length=100, default='cupom_cliente_tarragona', blank=True,
        verbose_name='Template Cliente Inativo',
        help_text='Template para reativacao de clientes inativos. Params: {{1}}=nome, {{2}}=cupom, {{3}}=desconto, {{4}}=validade'
    )

    # Parametros dos templates Meta (cupom/desconto/validade)
    meta_cupom_codigo = models.CharField(
        max_length=50, default='cupom10', blank=True,
        verbose_name='Codigo do Cupom',
        help_text='Codigo do cupom para os templates Meta (ex: cupom10)'
    )
    meta_cupom_desconto = models.CharField(
        max_length=10, default='10', blank=True,
        verbose_name='% Desconto',
        help_text='Percentual de desconto (ex: 10)'
    )
    meta_cupom_validade = models.CharField(
        max_length=50, default='dia 23/07/2026', blank=True,
        verbose_name='Validade do Cupom',
        help_text='Data de validade do cupom (ex: dia 23/07/2026)'
    )

    # Configuracoes visuais
    timezone = models.CharField(max_length=50, default='America/Sao_Paulo')
    logo = models.ImageField(
        upload_to='empresas/logos/',
        blank=True,
        null=True,
        verbose_name='Logo'
    )
    cor_primaria = models.CharField(
        max_length=7,
        default='#79aec8',
        verbose_name='Cor Primaria',
        help_text='Cor em hexadecimal (ex: #79aec8)'
    )

    # Metadados
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'empresas'
        verbose_name = 'Empresa'
        verbose_name_plural = 'Empresas'
        ordering = ['nome']
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['dominio']),
            models.Index(fields=['ativo']),
        ]

    def __str__(self):
        return self.nome

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.nome)
        if not self.dominio:
            self.dominio = self.slug
        super().save(*args, **kwargs)

    def get_full_domain(self):
        """Retorna dominio completo"""
        return f"{self.dominio}.posvendafacil.com.br"

    @property
    def link_consulta_pedido(self):
        """Link onde o cliente consulta o proprio pedido (sistema pos-venda)."""
        slug = self.dominio or self.slug
        return f"https://pedidos.posvendafacil.com.br/{slug}/consultar-pedido"

    @property
    def has_woocommerce_api(self):
        """Verifica se tem configuracao WooCommerce REST API"""
        return all([self.woo_store_url, self.woo_consumer_key, self.woo_consumer_secret])

    @property
    def has_woocommerce_config(self):
        """Verifica se tem configuracao WooCommerce completa (SSH ou direta)"""
        # Credenciais de banco são sempre necessárias
        has_db_config = all([
            self.woo_db_name,
            self.woo_db_user,
        ])

        # SSH é opcional - pode ser conexão direta
        has_ssh_config = all([
            self.woo_ssh_host,
            self.woo_ssh_user,
        ])

        # Conexão direta requer host externo (não localhost)
        has_direct_config = self.woo_db_host and self.woo_db_host not in ['127.0.0.1', 'localhost']

        return has_db_config and (has_ssh_config or has_direct_config)


class EmpresaUsuario(models.Model):
    """
    Relacao M2M entre Usuario e Empresa
    Permite um usuario ter acesso a multiplas empresas
    """
    ROLES = [
        ('owner', 'Proprietario'),
        ('admin', 'Administrador'),
        ('operator', 'Operador'),
        ('viewer', 'Visualizador'),
    ]

    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name='usuarios'
    )
    usuario = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='empresas'
    )
    role = models.CharField(
        max_length=20,
        choices=ROLES,
        default='operator',
        verbose_name='Funcao'
    )
    is_default = models.BooleanField(
        default=False,
        verbose_name='Empresa Padrao',
        help_text='Empresa que sera selecionada automaticamente ao logar'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'empresa_usuarios'
        verbose_name = 'Usuario da Empresa'
        verbose_name_plural = 'Usuarios da Empresa'
        unique_together = ['empresa', 'usuario']
        indexes = [
            models.Index(fields=['usuario', 'empresa']),
            models.Index(fields=['usuario', 'is_default']),
        ]

    def __str__(self):
        return f"{self.usuario.username} - {self.empresa.nome} ({self.get_role_display()})"

    def save(self, *args, **kwargs):
        # Se marcou como padrao, desmarcar outras
        if self.is_default:
            EmpresaUsuario.objects.filter(
                usuario=self.usuario,
                is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)
