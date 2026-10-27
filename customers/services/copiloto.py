"""
Copiloto de atendimento: dada uma conversa, devolve a resposta SUGERIDA.

Nunca envia nada — quem envia é o humano, depois de revisar.

Mesma regra para a extensão do WhatsApp Web e para o inbox: primeiro o agente da
empresa no neuraxo-agent (a Ana — LangGraph + RAG + persona, que conhece o site,
o frete e o catálogo); se ele estiver fora do ar, cai pro Claude do próprio CI
para não travar o atendente.
"""
import logging

from customers.services import neuraxo_copilot

logger = logging.getLogger(__name__)


class CopilotoSemContexto(Exception):
    """Não dá pra sugerir: a Ana está fora e não veio nenhuma mensagem."""


class CopilotoErro(Exception):
    """A IA falhou (rede, cota, resposta inválida)."""


def sugerir(empresa, nome, mensagens, telefone='', origem='extensao'):
    """
    Devolve {resposta, confianca, observacao, fonte, agente, escalar}.

    `mensagens`: [{'autor': 'cliente'|'loja', 'texto': str}] em ordem cronológica.
    A Ana também reconstrói a conversa pelo telefone, então `mensagens` pode vir
    vazia se houver `telefone`. O Claude de fallback precisa das mensagens.
    """
    from customers.services.sugestao_ia import sugerir_resposta

    if neuraxo_copilot.neuraxo_ativo(empresa):
        try:
            r = neuraxo_copilot.sugerir_via_neuraxo(empresa, nome, mensagens, telefone)
            logger.info(
                f"[Copiloto/{origem}] {empresa.slug}: sugestão via neuraxo-agent "
                f"(agente={r.get('agente')}, escalar={r.get('escalar')})"
            )
            return {
                'resposta': r['resposta'],
                'confianca': r['confianca'],
                'observacao': r['observacao'],
                'fonte': 'neuraxo-agent',
                'agente': r.get('agente', ''),
                'escalar': r.get('escalar', False),
            }
        except Exception as e:
            # Fora do ar não pode travar o atendimento: segue pro Claude local.
            logger.warning(f"[Copiloto/{origem}] neuraxo-agent falhou ({e}); usando Claude local")

    if not mensagens:
        raise CopilotoSemContexto('Ana indisponível e sem mensagens legíveis na conversa')

    try:
        s = sugerir_resposta(nome, mensagens, nome_loja=empresa.nome)
    except ValueError as e:
        raise CopilotoErro(str(e))
    except Exception as e:
        logger.exception(f"[Copiloto/{origem}] Falha na sugestão")
        raise CopilotoErro(f'Erro na IA: {e}')

    logger.info(f"[Copiloto/{origem}] {empresa.slug}: sugestão via Claude local "
                f"(confiança {s.confianca})")
    return {
        'resposta': s.resposta,
        'confianca': s.confianca,
        'observacao': s.observacao,
        'fonte': 'claude-local',
        'agente': '',
        'escalar': False,
    }
