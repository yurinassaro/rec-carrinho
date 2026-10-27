# Generated for Meta auto-response and cadastro_pedido template

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0016_add_telefone_monitoramento"),
    ]

    operations = [
        migrations.AddField(
            model_name="empresa",
            name="meta_resposta_automatica",
            field=models.TextField(
                blank=True,
                help_text="Texto enviado automaticamente quando cliente responde uma mensagem do bot. Deixe em branco para nao enviar.",
                verbose_name="Resposta Automatica (cliente responde)",
            ),
        ),
        migrations.AddField(
            model_name="empresa",
            name="meta_template_pedido_cadastro",
            field=models.CharField(
                blank=True,
                default="cadastro_pedido",
                help_text="Template enviado quando pedido e criado no site. Params: {{1}}=nome, {{2}}=numero do pedido",
                max_length=100,
                verbose_name="Template Cadastro Pedido",
            ),
        ),
    ]
