from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify


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

    # Mensagens WhatsApp personalizadas
    msg_whatsapp_lead = models.TextField(
        default='Olá {nome}, tudo bem ??',
        verbose_name='Mensagem WhatsApp - Leads',
        help_text='Mensagem padrão para leads. Use {nome} para inserir o nome do lead.'
    )
    msg_whatsapp_cart = models.TextField(
        default='Olá {nome}, tudo bem ??',
        verbose_name='Mensagem WhatsApp - Carrinho',
        help_text='Mensagem padrão para recuperação de carrinho. Use {nome} para inserir o nome do cliente.'
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
