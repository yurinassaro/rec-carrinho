# Default da resposta automatica + preenche empresas com o campo vazio.

from django.db import migrations, models


DEFAULT_RESPOSTA = (
    'Olá {nome}! Recebemos sua mensagem 🙏\n\n'
    'ℹ️ Este número é apenas de *avisos automáticos* e não realiza '
    'atendimento.\n\n'
    '📦 Para consultar o status do seu pedido, acesse:\n'
    '{consulta}\n\n'
    '⏱️ Se o seu pedido ainda não aparecer lá, aguarde até 24 horas — '
    'ele será sincronizado no sistema de consulta.\n\n'
    '📞 Para falar com um atendente, chame em nosso número oficial de '
    'atendimento: {atendimento_oficial}'
)


# Numero oficial de atendimento por empresa (preenchido na migracao).
ATENDIMENTO_OFICIAL = {
    'tarragona': '(16) 99704-6862',
}


def preencher_vazias(apps, schema_editor):
    """
    Preenche a resposta automatica das empresas com o campo vazio e o numero
    oficial de atendimento (quando conhecido por slug).
    """
    Empresa = apps.get_model('tenants', 'Empresa')
    for emp in Empresa.objects.all():
        campos = []
        atual = (emp.meta_resposta_automatica or '').strip()
        if not atual:
            emp.meta_resposta_automatica = DEFAULT_RESPOSTA
            campos.append('meta_resposta_automatica')
        oficial = ATENDIMENTO_OFICIAL.get(emp.slug)
        if oficial and not (emp.whatsapp_atendimento_oficial or '').strip():
            emp.whatsapp_atendimento_oficial = oficial
            campos.append('whatsapp_atendimento_oficial')
        if campos:
            emp.save(update_fields=campos)


def reverter(apps, schema_editor):
    # nao remove texto ja configurado; no-op seguro
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0018_bling_logistica_aguardando_retirada"),
    ]

    operations = [
        migrations.AddField(
            model_name="empresa",
            name="whatsapp_atendimento_oficial",
            field=models.CharField(
                blank=True,
                max_length=30,
                verbose_name="WhatsApp Oficial de Atendimento",
                help_text=(
                    "Numero OFICIAL de atendimento ao cliente (onde ele deve chamar). "
                    "O numero que envia os avisos automaticos NAO atende. "
                    "Ex: (16) 99999-9999"
                ),
            ),
        ),
        migrations.AlterField(
            model_name="empresa",
            name="meta_resposta_automatica",
            field=models.TextField(
                blank=True,
                default=DEFAULT_RESPOSTA,
                help_text=(
                    "Texto enviado automaticamente quando cliente responde uma mensagem do bot. "
                    "Deixe em branco para nao enviar. Variaveis: "
                    "{consulta} = link de consulta de pedido, {nome} = nome do cliente, "
                    "{atendimento_oficial} = numero oficial de atendimento, "
                    "{whatsapp_humano} = numero do atendente (encaminhamento interno)."
                ),
                verbose_name="Resposta Automatica (cliente responde)",
            ),
        ),
        migrations.RunPython(preencher_vazias, reverter),
    ]
