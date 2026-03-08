"""
Motor de Réguas de Comunicação.

Responsável por:
1. Avaliar quais réguas devem disparar para cada contato
2. Verificar frequency capping e blacklist
3. Enfileirar mensagens na FilaEnvio
4. Processar a fila e enviar mensagens
"""
import logging
from datetime import timedelta
from django.utils import timezone
from django.db.models import Count, Q

from comunicacao.models import (
    RegraComunicacao, ContatoBlacklist, FilaEnvio, EventoRecebido,
)
from customers.models import MensagemWhatsApp

logger = logging.getLogger(__name__)


def telefone_na_blacklist(empresa, telefone):
    """Verifica se telefone está na blacklist."""
    return ContatoBlacklist.objects.filter(
        empresa=empresa, telefone=telefone,
    ).exists()


def contar_msgs_semana(empresa, telefone):
    """Conta mensagens enviadas para este telefone nos últimos 7 dias."""
    uma_semana = timezone.now() - timedelta(days=7)
    return MensagemWhatsApp.objects.filter(
        empresa=empresa,
        destinatario_telefone=telefone,
        status__in=['enviado', 'entregue', 'lido'],
        created_at__gte=uma_semana,
    ).exclude(tipo='resposta_cliente').count()


def contar_envios_regra_telefone(regra, telefone):
    """Conta quantas vezes esta régua já enviou para este telefone."""
    return FilaEnvio.objects.filter(
        regra=regra,
        telefone=telefone,
        status='enviado',
    ).count()


def ultimo_envio_regra_telefone(regra, telefone):
    """Retorna datetime do último envio desta régua para este telefone."""
    ultimo = FilaEnvio.objects.filter(
        regra=regra,
        telefone=telefone,
        status='enviado',
    ).order_by('-processado_em').first()
    return ultimo.processado_em if ultimo else None


def ignorados_consecutivos(empresa, telefone):
    """
    Conta mensagens consecutivas não lidas (enviadas mas nunca marcadas como 'lido').
    Para de contar ao encontrar uma lida ou respondida.
    """
    msgs = MensagemWhatsApp.objects.filter(
        empresa=empresa,
        destinatario_telefone=telefone,
        canal='meta',
    ).exclude(
        tipo='resposta_cliente',
    ).order_by('-created_at')[:10]

    count = 0
    for msg in msgs:
        if msg.status in ('lido',) or msg.respondido:
            break
        if msg.status in ('enviado', 'entregue'):
            count += 1
    return count


def pode_enviar(regra, telefone):
    """
    Verifica todas as condições de frequency capping e blacklist.
    Retorna (pode, motivo).
    """
    empresa = regra.empresa

    # 1. Blacklist
    if telefone_na_blacklist(empresa, telefone):
        return False, 'blacklist'

    # 2. Max msgs por semana
    if contar_msgs_semana(empresa, telefone) >= regra.max_msgs_semana_telefone:
        return False, f'max_semana ({regra.max_msgs_semana_telefone})'

    # 3. Cooldown da régra
    if regra.cooldown_horas > 0:
        ultimo = ultimo_envio_regra_telefone(regra, telefone)
        if ultimo:
            cooldown_ate = ultimo + timedelta(hours=regra.cooldown_horas)
            if timezone.now() < cooldown_ate:
                return False, f'cooldown ({regra.cooldown_horas}h)'

    # 4. Max envios total por contato
    if regra.max_envios_total > 0:
        total = contar_envios_regra_telefone(regra, telefone)
        if total >= regra.max_envios_total:
            return False, f'max_total ({regra.max_envios_total})'

    # 5. Ignorados consecutivos → blacklist automática
    if regra.max_ignorados_consecutivos > 0:
        ign = ignorados_consecutivos(empresa, telefone)
        if ign >= regra.max_ignorados_consecutivos:
            # Adicionar à blacklist automaticamente
            ContatoBlacklist.objects.get_or_create(
                empresa=empresa,
                telefone=telefone,
                defaults={
                    'motivo': 'too_many_ignored',
                    'detalhes': f'{ign} mensagens ignoradas consecutivamente',
                },
            )
            return False, f'ignorados ({ign}x)'

    # 6. Max envios da régra por dia (anti-spam global)
    if regra.max_envios_dia > 0:
        hoje_inicio = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        envios_hoje = FilaEnvio.objects.filter(
            regra=regra,
            status='enviado',
            processado_em__gte=hoje_inicio,
        ).count()
        if envios_hoje >= regra.max_envios_dia:
            return False, f'max_dia ({regra.max_envios_dia})'

    return True, 'ok'


def calcular_horario_envio(regra, momento_gatilho=None):
    """
    Calcula quando enviar, respeitando delay + horário comercial.
    """
    agora = momento_gatilho or timezone.now()
    envio = agora + timedelta(hours=regra.delay_horas)

    # Ajustar para horário comercial
    hora_envio = envio.time()
    if hora_envio < regra.horario_inicio:
        envio = envio.replace(
            hour=regra.horario_inicio.hour,
            minute=regra.horario_inicio.minute,
            second=0, microsecond=0,
        )
    elif hora_envio > regra.horario_fim:
        # Agendar para o dia seguinte no horário de início
        envio = (envio + timedelta(days=1)).replace(
            hour=regra.horario_inicio.hour,
            minute=regra.horario_inicio.minute,
            second=0, microsecond=0,
        )

    # Ajustar dia da semana se necessário
    if regra.dias_semana:
        while envio.weekday() not in regra.dias_semana:
            envio += timedelta(days=1)
            envio = envio.replace(
                hour=regra.horario_inicio.hour,
                minute=regra.horario_inicio.minute,
            )

    return envio


def enfileirar(regra, telefone, nome, lead=None, cart=None, customer=None,
               momento_gatilho=None):
    """
    Verifica capping e enfileira mensagem se permitido.
    Retorna (FilaEnvio ou None, motivo).
    """
    from customers.services.wapi import formatar_telefone

    telefone_fmt = formatar_telefone(telefone)
    if not telefone_fmt:
        return None, 'telefone_invalido'

    ok, motivo = pode_enviar(regra, telefone_fmt)
    if not ok:
        logger.debug(
            f"[{regra.empresa.slug}] Bloqueado: {telefone_fmt} - {regra.nome} - {motivo}"
        )
        return None, motivo

    agendar_para = calcular_horario_envio(regra, momento_gatilho)

    # Evitar duplicatas na fila
    ja_na_fila = FilaEnvio.objects.filter(
        regra=regra,
        telefone=telefone_fmt,
        status='pendente',
    ).exists()
    if ja_na_fila:
        return None, 'ja_na_fila'

    item = FilaEnvio.objects.create(
        empresa=regra.empresa,
        regra=regra,
        telefone=telefone_fmt,
        nome=nome,
        lead=lead,
        cart=cart,
        customer=customer,
        agendar_para=agendar_para,
    )

    logger.info(
        f"[{regra.empresa.slug}] Enfileirado: {telefone_fmt} - {regra.nome} "
        f"- para {agendar_para.strftime('%d/%m %H:%M')}"
    )
    return item, 'enfileirado'


def avaliar_regras_para_gatilho(empresa, gatilho, lead=None, cart=None,
                                 customer=None, telefone=None, nome=None):
    """
    Busca todas as réguas ativas para este gatilho e empresa.
    Avalia condições e enfileira quando aplicável.
    Retorna lista de (FilaEnvio, motivo) para cada régra avaliada.
    """
    regras = RegraComunicacao.objects.filter(
        empresa=empresa,
        gatilho=gatilho,
        ativo=True,
    ).order_by('etapa', 'prioridade')

    if not regras.exists():
        return []

    # Resolver telefone e nome
    if not telefone:
        if lead:
            telefone = lead.whatsapp
            nome = nome or (lead.nome.split()[0] if lead.nome else 'Cliente')
        elif cart and cart.customer:
            telefone = cart.customer.phone or ''
            nome = nome or (cart.customer.first_name.split()[0] if cart.customer.first_name else 'Cliente')
        elif customer:
            telefone = customer.phone or ''
            nome = nome or (customer.first_name.split()[0] if customer.first_name else 'Cliente')

    if not telefone:
        return []

    resultados = []
    for regra in regras:
        # Multi-step: etapa > 1 só dispara se etapa anterior foi enviada
        if regra.etapa > 1:
            etapa_anterior = RegraComunicacao.objects.filter(
                empresa=empresa,
                gatilho=gatilho,
                etapa=regra.etapa - 1,
                ativo=True,
            ).first()
            if etapa_anterior:
                from customers.services.wapi import formatar_telefone
                tel_fmt = formatar_telefone(telefone)
                enviou_anterior = FilaEnvio.objects.filter(
                    regra=etapa_anterior,
                    telefone=tel_fmt,
                    status='enviado',
                ).exists()
                if not enviou_anterior:
                    resultados.append((None, 'etapa_anterior_pendente'))
                    continue

        # Avaliar condições extras (JSON)
        if not _avaliar_condicoes(regra, lead=lead, cart=cart, customer=customer):
            resultados.append((None, 'condicao_nao_atendida'))
            continue

        item, motivo = enfileirar(
            regra, telefone, nome,
            lead=lead, cart=cart, customer=customer,
        )
        resultados.append((item, motivo))

    return resultados


def _avaliar_condicoes(regra, lead=None, cart=None, customer=None):
    """
    Avalia condições extras da régra (JSON).
    Suporta: min_cart_value, min_orders, max_orders, min_score, min_days_inactive, etc.
    """
    cond = regra.condicoes
    if not cond:
        return True

    # Condições de carrinho
    if 'min_cart_value' in cond and cart:
        if float(cart.cart_total) < cond['min_cart_value']:
            return False

    # Condições de cliente
    c = customer or (lead.related_customer if lead else None)
    if c:
        if 'min_orders' in cond and (c.completed_orders or 0) < cond['min_orders']:
            return False
        if 'max_orders' in cond and (c.completed_orders or 0) > cond['max_orders']:
            return False
        if 'min_score' in cond and (c.score or 0) < cond['min_score']:
            return False
        if 'min_days_inactive' in cond and (c.days_since_last_purchase or 0) < cond['min_days_inactive']:
            return False
        if 'min_total_spent' in cond and float(c.total_spent or 0) < cond['min_total_spent']:
            return False

    return True
