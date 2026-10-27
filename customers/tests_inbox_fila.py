"""
Testes da fila do inbox: janela de 24h da Meta, tempo de espera, filtros e ordem.

As funções testadas aqui são puras (recebem lista de dicts, não queryset), então
rodam em SimpleTestCase — sem banco. O que elas protegem é a regra de atendimento:
quem perguntou e não foi respondido não pode sumir da lista, e a janela de 24h
precisa ser contada da última mensagem DO CLIENTE (é ela que libera texto livre).
"""
from datetime import timedelta

from django.test import SimpleTestCase
from django.utils import timezone

from customers.views_inbox import (
    _agrupar_conversas,
    _dur_label,
    _filtrar_ordenar_conversas,
    _telefone_canonico,
)

AGORA = timezone.now()


def msg(telefone, minutos_atras, tipo='resposta_cliente', respondida=False,
        nome='', texto='oi', template=''):
    """Um registro como o .values() da MensagemWhatsApp entrega."""
    return {
        'id': abs(hash((telefone, minutos_atras, tipo, texto))) % 10 ** 9,
        'destinatario_telefone': telefone,
        'destinatario_nome': nome,
        'mensagem_texto': texto,
        'template_name': template,
        'created_at': AGORA - timedelta(minutes=minutos_atras),
        'tipo': tipo,
        'encaminhado_humano': respondida,
    }


def agrupar(registros):
    return _agrupar_conversas(registros, AGORA)


def uma(registros):
    grupos = agrupar(registros)
    assert len(grupos) == 1, f'esperava 1 conversa, veio {len(grupos)}'
    return list(grupos.values())[0]


class DurLabelTest(SimpleTestCase):
    def test_rotulos(self):
        self.assertEqual(_dur_label(0), '0min')
        self.assertEqual(_dur_label(45), '45min')
        self.assertEqual(_dur_label(60), '1h')
        self.assertEqual(_dur_label(200), '3h20')
        self.assertEqual(_dur_label(60 * 24), '1d')
        self.assertEqual(_dur_label(60 * 24 * 14), '2sem')

    def test_negativo_nao_estoura(self):
        self.assertEqual(_dur_label(-5), '0min')


class JanelaEEsperaTest(SimpleTestCase):
    def test_cliente_perguntou_ha_30min_sem_resposta(self):
        g = uma([msg('5516999990001', 30)])
        self.assertTrue(g['janela_aberta'])
        self.assertEqual(g['nao_respondidas'], 1)
        self.assertAlmostEqual(g['espera_min'], 30, delta=1)
        self.assertAlmostEqual(g['janela_resta_min'], 24 * 60 - 30, delta=1)

    def test_cliente_perguntou_ha_40h_sem_resposta_janela_fechada(self):
        g = uma([msg('5516999990002', 40 * 60)])
        self.assertFalse(g['janela_aberta'])
        self.assertEqual(g['janela_resta_min'], 0)
        self.assertEqual(g['nao_respondidas'], 1)
        self.assertAlmostEqual(g['espera_min'], 40 * 60, delta=1)

    def test_cliente_perguntou_ha_23h_janela_quase_fechando(self):
        """O caso do selo amarelo: <= 120 min restantes."""
        g = uma([msg('5516999990003', 23 * 60)])
        self.assertTrue(g['janela_aberta'])
        self.assertAlmostEqual(g['janela_resta_min'], 60, delta=1)
        self.assertLessEqual(g['janela_resta_min'], 120)

    def test_cliente_respondido_ha_2h_nao_entra_na_fila(self):
        g = uma([
            msg('5516999990004', 125, respondida=True),
            msg('5516999990004', 120, tipo='promocao'),
        ])
        self.assertTrue(g['janela_aberta'])
        self.assertEqual(g['nao_respondidas'], 0)
        self.assertEqual(g['espera_min'], 0)

    def test_conversa_so_com_template_nosso_fica_fechada(self):
        g = uma([msg('5516999990005', 10, tipo='promocao', texto='', template='promo_x')])
        self.assertFalse(g['janela_aberta'])
        self.assertEqual(g['nao_respondidas'], 0)
        self.assertEqual(g['espera_min'], 0)

    def test_espera_conta_a_mensagem_mais_antiga_sem_resposta(self):
        """Cliente mandou 3 mensagens: a janela vem da última, a espera da primeira."""
        g = uma([
            msg('5516999990006', 300),
            msg('5516999990006', 180),
            msg('5516999990006', 60),
        ])
        self.assertEqual(g['nao_respondidas'], 3)
        self.assertAlmostEqual(g['espera_min'], 300, delta=1)
        self.assertAlmostEqual(g['janela_resta_min'], 24 * 60 - 60, delta=1)


class AgrupamentoTelefoneTest(SimpleTestCase):
    def test_canonico_ignora_ddi_e_9_movel(self):
        self.assertEqual(
            _telefone_canonico('5516999990001'),
            _telefone_canonico('551699990001'),
        )

    def test_mesmo_numero_com_e_sem_9_cai_numa_conversa(self):
        """A Meta devolve inbound sem o 9; não pode virar duas conversas."""
        grupos = agrupar([
            msg('551699990001', 10, nome='Maria'),          # sem o 9, mais recente
            msg('5516999990001', 90, tipo='promocao'),      # com o 9, mais antiga
        ])
        self.assertEqual(len(grupos), 1)
        g = list(grupos.values())[0]
        self.assertEqual(g['total'], 2)
        self.assertEqual(g['nome'], 'Maria')

    def test_ultima_mensagem_nao_depende_da_ordem_de_entrada(self):
        """
        A view junta duas listas em ordens opostas (recentes desc + pendentes asc).
        A 'última mensagem' tem que ser a de maior created_at, não a última do input.
        """
        recente = msg('5516999990001', 5, tipo='promocao', texto='enviado agora')
        antiga = msg('551699990001', 60 * 50, texto='pergunta velha')
        for rotulo, entrada in [('recente primeiro', [recente, antiga]),
                                ('antiga primeiro', [antiga, recente])]:
            with self.subTest(entrada=rotulo):
                g = uma(entrada)
                self.assertEqual(g['ultima_msg'], 'enviado agora')
                self.assertEqual(g['tipo'], 'promocao')

    def test_telefone_vazio_e_descartado(self):
        self.assertEqual(agrupar([msg('', 10), msg('abc', 10)]), {})


class FiltroOrdemTest(SimpleTestCase):
    def setUp(self):
        # pendente_antigo: perguntou há 40h, janela fechada, maior espera
        # pendente_novo:   perguntou há 30min, janela aberta
        # quieto:          respondido, nada esperando, mensagem mais recente
        self.todas = list(agrupar([
            msg('5516900000001', 40 * 60, nome='Antigo'),
            msg('5516900000002', 30, nome='Novo'),
            msg('5516900000003', 125, nome='Quieto', respondida=True),
            msg('5516900000003', 2, tipo='promocao', texto='template nosso'),
        ]).values())
        self.assertEqual(len(self.todas), 3)

    def nomes(self, filtro='', ordem=''):
        return [g['nome'] for g in _filtrar_ordenar_conversas(self.todas, filtro, ordem)]

    def test_ordem_padrao_e_mais_recente_primeiro(self):
        self.assertEqual(self.nomes(), ['Quieto', 'Novo', 'Antigo'])

    def test_filtro_nao_respondidos_com_ordem_antigos_pesca_o_esquecido(self):
        """O caso que o filtro existe pra resolver: quem espera há mais tempo no topo."""
        self.assertEqual(self.nomes('nao_respondidos', 'antigos'), ['Antigo', 'Novo'])

    def test_ordem_antigos_sem_filtro_joga_quem_nao_espera_pro_fim(self):
        self.assertEqual(self.nomes('', 'antigos'), ['Antigo', 'Novo', 'Quieto'])

    def test_filtro_janela_aberta_exclui_a_fechada(self):
        nomes = self.nomes('janela_aberta', 'janela')
        self.assertNotIn('Antigo', nomes)
        self.assertEqual(set(nomes), {'Novo', 'Quieto'})

    def test_ordem_janela_poe_a_que_fecha_antes_primeiro(self):
        # Quieto falou há 125min, Novo há 30min → Quieto fecha antes.
        self.assertEqual(self.nomes('janela_aberta', 'janela'), ['Quieto', 'Novo'])

    def test_ordem_janela_joga_fechadas_pro_fim(self):
        self.assertEqual(self.nomes('', 'janela')[-1], 'Antigo')

    def test_filtro_desconhecido_cai_em_todas(self):
        self.assertEqual(len(self.nomes('xpto')), 3)
