from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0016_merge_20260326_1531"),
    ]

    operations = [
        migrations.AlterField(
            model_name="mensagemwhatsapp",
            name="tipo",
            field=models.CharField(
                choices=[
                    ("lead", "Lead Novo (nao cliente)"),
                    ("lead_cliente", "Lead Ja Cliente"),
                    ("cart", "Carrinho Abandonado"),
                    ("cliente_inativo", "Cliente Inativo (reativacao)"),
                    ("pedido_novo", "Pedido Novo"),
                    ("pedido_processando", "Pedido Processando"),
                    ("pedido_embalado", "Pedido Embalado"),
                    ("pedido_transito", "Pedido em Transito"),
                    ("pedido_concluido", "Pedido Concluido"),
                    ("pedido_cancelado", "Pedido Cancelado"),
                    ("resposta_cliente", "Resposta do Cliente"),
                    ("auto_resposta", "Auto-resposta do Bot"),
                    ("atendimento_humano", "Atendimento Humano (Inbox)"),
                ],
                max_length=30,
            ),
        ),
    ]
