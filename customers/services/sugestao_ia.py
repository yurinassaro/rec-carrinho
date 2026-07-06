"""
Copiloto de atendimento via IA (Claude Sonnet).

Recebe o histórico recente de UMA conversa do WhatsApp (lido pela extensão
Chrome direto do DOM do WhatsApp Web) e gera uma SUGESTÃO de resposta que o
atendente revisa antes de enviar (humano no controle — nunca envia sozinho).

Modelo: claude-sonnet-4-6 (mesmo da triagem). Chave: ANTHROPIC_API_KEY do env.
"""
import logging
from typing import Literal

from decouple import config
from pydantic import BaseModel

logger = logging.getLogger(__name__)

MODELO = "claude-sonnet-4-6"
MAX_MENSAGENS = 25          # janela de contexto da conversa
MAX_CHARS_POR_MSG = 800


def _system_prompt(nome_loja: str) -> str:
    return (
        f"Você é um atendente experiente da {nome_loja}, uma loja de calçados "
        "masculinos em couro legítimo, produzidos na própria fábrica em Franca-SP. "
        "Você recebe o histórico recente de uma conversa de WhatsApp e escreve a "
        "PRÓXIMA resposta da loja ao cliente.\n\n"
        "REGRAS DA RESPOSTA:\n"
        "- Português brasileiro, tom cordial e direto, como WhatsApp real (frases "
        "curtas, no máximo 1-2 emojis).\n"
        "- Responda exatamente o que o cliente perguntou/pediu. Não invente "
        "informação que não está na conversa (prazo, preço, estoque, código de "
        "rastreio). Se faltar um dado necessário, a resposta deve dizer que vai "
        "verificar e retornar — e aponte isso na observacao.\n"
        "- Se o cliente relata problema/atraso, reconheça, peça desculpa uma vez "
        "e diga o próximo passo concreto.\n"
        "- Se o cliente mandou áudio/imagem que você não pode ver (marcado como "
        "'[áudio]' ou '[imagem]'), a resposta deve pedir gentilmente a informação "
        "por texto OU indicar que vai ouvir/ver e já retorna.\n"
        "- Nunca prometa desconto/cupom que não esteja mencionado na conversa.\n"
        "- Assine como a loja, não como pessoa (sem inventar nome de atendente).\n\n"
        "Além da resposta, avalie sua confiança:\n"
        "- 'alta': a conversa tem tudo que você precisa pra responder bem.\n"
        "- 'media': dá pra responder, mas o atendente deve conferir um detalhe.\n"
        "- 'baixa': falta contexto importante (pedido, rastreio, cadastro) — o "
        "atendente PRECISA completar antes de enviar."
    )


class Sugestao(BaseModel):
    resposta: str
    confianca: Literal["alta", "media", "baixa"]
    observacao: str  # 1 frase pro atendente (o que conferir antes de enviar); '' se nada


def _get_client():
    import anthropic

    api_key = config("ANTHROPIC_API_KEY", default="")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY não configurada no ambiente.")
    return anthropic.Anthropic(api_key=api_key)


def sugerir_resposta(nome_contato: str, mensagens: list, nome_loja: str = "Tarragona Calçados") -> Sugestao:
    """
    Gera a sugestão de resposta para uma conversa.

    mensagens: lista cronológica [{"autor": "cliente"|"loja", "texto": "..."}]
    (a extensão manda as últimas ~15-25 lidas do DOM).
    """
    recentes = mensagens[-MAX_MENSAGENS:]
    linhas = []
    for m in recentes:
        autor = 'CLIENTE' if (m.get('autor') or 'cliente') == 'cliente' else 'LOJA'
        texto = (m.get('texto') or '').strip()[:MAX_CHARS_POR_MSG]
        if texto:
            linhas.append(f"{autor}: {texto}")
    if not linhas:
        raise ValueError("Conversa vazia — nada para sugerir.")

    conteudo = (
        f"Cliente: {nome_contato or 'não identificado'}\n\n"
        "Conversa (da mais antiga para a mais recente):\n"
        + "\n".join(linhas)
        + "\n\nEscreva a próxima resposta da loja."
    )

    client = _get_client()
    resp = client.messages.parse(
        model=MODELO,
        max_tokens=512,
        system=_system_prompt(nome_loja),
        messages=[{"role": "user", "content": conteudo}],
        output_format=Sugestao,
    )
    return resp.parsed_output
