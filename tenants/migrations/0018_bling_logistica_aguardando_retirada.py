# Generated for Bling logística (objetos de postagem) - aguardando retirada

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0017_meta_resposta_automatica_e_cadastro"),
    ]

    operations = [
        migrations.AddField(
            model_name="empresa",
            name="bling_logistica_id",
            field=models.CharField(
                blank=True,
                max_length=50,
                help_text='ID da logística no Bling para listar objetos "Aguardando retirada" '
                          "(veja na URL integracoes_logisticas.php?logisticId=...)",
                verbose_name="ID Logística (Objetos de postagem)",
            ),
        ),
        migrations.AddField(
            model_name="empresa",
            name="msg_whatsapp_aguardando_retirada",
            field=models.TextField(
                blank=True,
                help_text="Variáveis: {nome}, {pedido}, {codigo}, {link}",
                default=(
                    "Olá {nome}! 📦 Seu pedido #{pedido} já chegou e está *disponível para "
                    "retirada* na agência dos Correios.\n\n"
                    "Código de rastreio: *{codigo}*\n"
                    "Acompanhe aqui: {link}\n\n"
                    "Não esqueça de levar um documento com foto. 😊"
                ),
                verbose_name="Mensagem Aguardando Retirada",
            ),
        ),
    ]
