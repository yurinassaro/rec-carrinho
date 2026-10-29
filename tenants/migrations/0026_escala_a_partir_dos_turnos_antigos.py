"""
Converte a escala velha (atendente da manhã / da tarde + hora da troca) nas
linhas da escala nova, pra ninguém ter que redigitar.

A escala velha não sabia o dia da semana, então o que ela descrevia era, na
prática, a semana útil — é assim que a conversão trata.
"""
from datetime import time

from django.db import migrations


def criar_turnos(apps, schema_editor):
    Empresa = apps.get_model('tenants', 'Empresa')
    Turno = apps.get_model('tenants', 'TurnoAtendente')

    for e in Empresa.objects.all():
        if Turno.objects.filter(empresa=e).exists():
            continue
        manha = (e.atendente_manha or '').strip()
        tarde = (e.atendente_tarde or '').strip()
        if not (manha or tarde):
            continue
        troca = e.hora_troca_atendente if e.hora_troca_atendente is not None else 15
        troca = max(0, min(23, int(troca)))

        semana = dict(seg=True, ter=True, qua=True, qui=True, sex=True,
                      sab=False, dom=False)
        if manha:
            Turno.objects.create(
                empresa=e, nome=manha, ordem=1,
                hora_inicio=time(8, 0), hora_fim=time(troca, 0), **semana
            )
        if tarde:
            Turno.objects.create(
                empresa=e, nome=tarde, ordem=2,
                hora_inicio=time(troca, 0), hora_fim=time(22, 0), **semana
            )


def apagar_turnos(apps, schema_editor):
    # Os campos antigos continuam no banco, então desfazer é só limpar a escala.
    apps.get_model('tenants', 'TurnoAtendente').objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [('tenants', '0025_escala_atendimento')]

    operations = [migrations.RunPython(criar_turnos, apagar_turnos)]
