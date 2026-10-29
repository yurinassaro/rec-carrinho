"""
Escala de atendimento: quem assina a mensagem em cada dia e horário.

A escala real da loja (29/10/2026) é a referência dos testes:
  Yasmin  seg a sex  08:00–15:00  (cobre até 14:59)
  André   seg a sex  15:00–22:00
  sábado  Yuri ou André — "geralmente", então a escala dá o padrão e quem
          está na cadeira troca no seletor do inbox.
"""
from datetime import datetime, time
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from tenants.models import Empresa, TurnoAtendente

SEMANA = dict(seg=True, ter=True, qua=True, qui=True, sex=True, sab=False, dom=False)
SO_SABADO = dict(seg=False, ter=False, qua=False, qui=False, sex=False, sab=True, dom=False)


def _em(ano, mes, dia, hora, minuto=0):
    """Um instante no fuso da aplicação, pra fingir 'agora'."""
    return timezone.make_aware(datetime(ano, mes, dia, hora, minuto))


class EscalaTest(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(
            nome='Loja', slug='loja-escala', ativo=True, woo_webhook_secret='s',
        )
        TurnoAtendente.objects.create(
            empresa=self.empresa, nome='Yasmin', ordem=1,
            hora_inicio=time(8, 0), hora_fim=time(15, 0), **SEMANA)
        TurnoAtendente.objects.create(
            empresa=self.empresa, nome='Andre', ordem=2,
            hora_inicio=time(15, 0), hora_fim=time(22, 0), **SEMANA)
        TurnoAtendente.objects.create(
            empresa=self.empresa, nome='Yuri', ordem=3,
            hora_inicio=time(8, 0), hora_fim=time(13, 0), **SO_SABADO)

    def plantao_em(self, quando):
        with patch('django.utils.timezone.localtime', return_value=quando):
            return self.empresa.atendente_de_plantao

    # 29/10/2026 é quinta; 31/10/2026 é sábado; 01/11/2026 é domingo.

    def test_manha_de_semana_e_a_yasmin(self):
        for hora, minuto in [(8, 0), (10, 30), (14, 59)]:
            self.assertEqual(
                self.plantao_em(_em(2026, 10, 29, hora, minuto)), 'Yasmin',
                f'{hora}:{minuto:02d}')

    def test_quinze_em_ponto_ja_e_o_andre(self):
        """O fim do turno não conta: 08–15 cobre até 14:59."""
        self.assertEqual(self.plantao_em(_em(2026, 10, 29, 14, 59)), 'Yasmin')
        self.assertEqual(self.plantao_em(_em(2026, 10, 29, 15, 0)), 'Andre')

    def test_tarde_de_semana_e_o_andre(self):
        for hora in (15, 18, 21):
            self.assertEqual(self.plantao_em(_em(2026, 10, 29, hora)), 'Andre', str(hora))

    def test_sabado_tem_escala_propria(self):
        self.assertEqual(self.plantao_em(_em(2026, 10, 31, 9)), 'Yuri')

    def test_sabado_fora_do_horario_cai_em_quem_fechou_o_turno(self):
        """Depois das 13h de sábado ninguém está de plantão. Assinar com quem
        acabou de sair é melhor do que não assinar."""
        self.assertEqual(self.plantao_em(_em(2026, 10, 31, 17)), 'Yuri')

    def test_domingo_sem_escala_nao_quebra(self):
        self.assertIn(self.plantao_em(_em(2026, 11, 1, 10)), ['Yasmin', 'Andre', 'Yuri'])

    def test_madrugada_de_semana_cai_em_quem_fechou(self):
        self.assertEqual(self.plantao_em(_em(2026, 10, 29, 23)), 'Andre')

    def test_antes_de_abrir_aponta_pra_quem_abre(self):
        self.assertEqual(self.plantao_em(_em(2026, 10, 29, 6)), 'Yasmin')

    # --- lista branca -----------------------------------------------------

    def test_atendentes_traz_todo_mundo_da_escala(self):
        """O do sábado precisa aparecer num dia de semana também: é nome
        válido pra assinar, mesmo fora do turno dele."""
        self.assertEqual(self.empresa.atendentes, ['Yasmin', 'Andre', 'Yuri'])

    def test_campos_antigos_nao_poluem_a_lista_quando_ha_escala(self):
        """Resquício do cadastro velho não pode aparecer no seletor: daria
        o mesmo nome duas vezes (ex: 'André' e 'Andre')."""
        self.empresa.atendente_manha = 'Yasmin'
        self.empresa.atendente_tarde = 'Andre Antigo'
        self.empresa.save(update_fields=['atendente_manha', 'atendente_tarde'])
        self.assertEqual(self.empresa.atendentes, ['Yasmin', 'Andre', 'Yuri'])

    def test_turno_inativo_sai_da_lista(self):
        TurnoAtendente.objects.filter(nome='Yuri').update(ativo=False)
        self.empresa.refresh_from_db()
        self.assertNotIn('Yuri', self.empresa.atendentes)

    def test_mesma_pessoa_em_dois_turnos_aparece_uma_vez(self):
        TurnoAtendente.objects.create(
            empresa=self.empresa, nome='Andre', ordem=4,
            hora_inicio=time(8, 0), hora_fim=time(13, 0), **SO_SABADO)
        self.empresa.refresh_from_db()
        self.assertEqual(self.empresa.atendentes.count('Andre'), 1)

    # --- o que a tela mostra ---------------------------------------------

    def test_descricao_legivel(self):
        self.assertEqual(
            TurnoAtendente.objects.get(nome='Yasmin').descricao,
            'seg a sex, 08h–15h')
        self.assertEqual(
            TurnoAtendente.objects.get(nome='Yuri').descricao,
            'sáb, 08h–13h')

    def test_descricao_com_minutos(self):
        t = TurnoAtendente.objects.get(nome='Yasmin')
        t.hora_fim = time(14, 59)
        self.assertIn('14h59', t.descricao)

    def test_escala_resumida_junta_os_turnos_da_pessoa(self):
        TurnoAtendente.objects.create(
            empresa=self.empresa, nome='Andre', ordem=4,
            hora_inicio=time(8, 0), hora_fim=time(13, 0), **SO_SABADO)
        self.empresa.refresh_from_db()
        self.assertIn('·', self.empresa.escala_resumida['Andre'])


class PlantaoTest(TestCase):
    """Quem atende fora do próprio horário assina com '(plantão)'."""

    def setUp(self):
        self.empresa = Empresa.objects.create(
            nome='Loja', slug='loja-plantao', ativo=True, woo_webhook_secret='s',
            inbox_prefixo_atendente='sempre',
        )
        TurnoAtendente.objects.create(
            empresa=self.empresa, nome='Yasmin', ordem=1,
            hora_inicio=time(8, 0), hora_fim=time(15, 0), **SEMANA)
        TurnoAtendente.objects.create(
            empresa=self.empresa, nome='Andre', ordem=2,
            hora_inicio=time(15, 0), hora_fim=time(22, 0), **SEMANA)
        TurnoAtendente.objects.create(
            empresa=self.empresa, nome='Yuri', ordem=3,
            hora_inicio=time(14, 0), hora_fim=time(20, 0), **SO_SABADO)

    def em(self, quando, nome):
        from customers.views_inbox import _assinatura_atendente
        with patch('django.utils.timezone.localtime', return_value=quando):
            return _assinatura_atendente(self.empresa, nome, ['5516999990001'])

    def test_dentro_do_horario_assina_limpo(self):
        # quinta 10h — turno da Yasmin
        self.assertEqual(self.em(_em(2026, 10, 29, 10), 'Yasmin'), '*Atendente Yasmin*')

    def test_fora_do_horario_vira_plantao(self):
        # quinta 10h, mas quem responde é o Andre (turno dele é 15h–22h)
        self.assertEqual(self.em(_em(2026, 10, 29, 10), 'Andre'),
                         '*Atendente Andre (plantão)*')

    def test_dono_respondendo_no_domingo_e_plantao(self):
        self.assertEqual(self.em(_em(2026, 11, 1, 21), 'Yuri'),
                         '*Atendente Yuri (plantão)*')

    def test_sabado_no_horario_dele_assina_limpo(self):
        # sábado 15h — dentro do 14h–20h do Yuri
        self.assertEqual(self.em(_em(2026, 10, 31, 15), 'Yuri'), '*Atendente Yuri*')

    def test_sabado_antes_das_14_e_plantao(self):
        self.assertEqual(self.em(_em(2026, 10, 31, 9), 'Yuri'),
                         '*Atendente Yuri (plantão)*')

    def test_em_turno_responde_certo(self):
        with patch('django.utils.timezone.localtime', return_value=_em(2026, 10, 29, 10)):
            self.assertTrue(self.empresa.em_turno('Yasmin'))
            self.assertFalse(self.empresa.em_turno('Andre'))
            self.assertEqual(self.empresa.atendentes_em_turno, ['Yasmin'])

    def test_empresa_sem_escala_nunca_marca_plantao(self):
        """Sem horário cadastrado não dá pra dizer que alguém está fora dele."""
        e = Empresa.objects.create(
            nome='Sem escala', slug='sem-escala', ativo=True, woo_webhook_secret='s',
            atendente_manha='Maria', inbox_prefixo_atendente='sempre')
        self.assertTrue(e.em_turno('Maria'))

    def test_plantao_nao_quebra_o_modo_primeira(self):
        """A marca '*Atendente ' tem que continuar sendo achada no histórico,
        senão o modo 'primeira' assina de novo toda mensagem."""
        from customers.models import MensagemWhatsApp
        from customers.views_inbox import PREFIXO_MARCA
        self.empresa.inbox_prefixo_atendente = 'primeira'
        MensagemWhatsApp.objects.create(
            empresa=self.empresa, tipo='atendimento_humano', canal='meta',
            status='entregue', destinatario_telefone='5516999990001',
            mensagem_texto='*Atendente Andre (plantão)*\nbom dia')
        self.assertIn(PREFIXO_MARCA, '*Atendente Andre (plantão)*')
        self.assertEqual(self.em(_em(2026, 10, 29, 10), 'Andre'), '')


class TurnoQueViraANoiteTest(TestCase):
    def test_turno_cruzando_meia_noite(self):
        e = Empresa.objects.create(
            nome='Noturna', slug='noturna', ativo=True, woo_webhook_secret='s')
        t = TurnoAtendente.objects.create(
            empresa=e, nome='Plantao', hora_inicio=time(22, 0), hora_fim=time(2, 0),
            seg=True, ter=True, qua=True, qui=True, sex=True, sab=True, dom=True)
        self.assertTrue(t.contem(time(23, 0)))
        self.assertTrue(t.contem(time(1, 0)))
        self.assertFalse(t.contem(time(12, 0)))


class SemEscalaUsaOsCamposAntigosTest(TestCase):
    """Empresa que ainda não montou a escala continua funcionando."""

    def test_cai_nos_campos_antigos(self):
        e = Empresa.objects.create(
            nome='Antiga', slug='antiga', ativo=True, woo_webhook_secret='s',
            atendente_manha='Maria', atendente_tarde='Joao', hora_troca_atendente=15)
        with patch('django.utils.timezone.localtime', return_value=_em(2026, 10, 29, 9)):
            self.assertEqual(e.atendente_de_plantao, 'Maria')
        with patch('django.utils.timezone.localtime', return_value=_em(2026, 10, 29, 16)):
            self.assertEqual(e.atendente_de_plantao, 'Joao')
        self.assertEqual(e.atendentes, ['Maria', 'Joao'])
