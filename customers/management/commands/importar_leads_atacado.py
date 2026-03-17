"""
Importa leads de atacado do Excel exportado do ClickUp.
Uso: python manage.py importar_leads_atacado /caminho/arquivo.xlsx --empresa=tarragona
"""
import re
from datetime import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from customers.models import LeadAtacado
from tenants.models import Empresa


# Mapa de status do ClickUp para o CRM
STATUS_MAP = {
    'to do': 'novo',
    'conversando': 'conversando',
    'conversado-podencial': 'potencial',
    'conversado-nãopotencial': 'nao_potencial',
    'passado peixinho': 'passado_vendedor',
    'curioso': 'curioso',
    'virou cliente': 'convertido',
}

# Mapa de status de negócio
STATUS_EMPRESA_MAP = {
    'tenho uma empresa - vendo calçados': 'tenho_empresa_vendo_calcados',
    'tenho uma empresa - não vendo sapatos': 'tenho_empresa_nao_vendo_sapatos',
    'não tenho uma empresa - vendo sapatos': 'nao_tenho_empresa_vendo_sapatos',
    'não tenho uma empresa - não vendo sapatos': 'nao_tenho_empresa_nao_vendo_sapatos',
}

# Mapa de planos
PLANO_MAP = {
    'sortidos (acima de 12 pares)': 'sortidos',
    'sortidos (acima de 36 pares)': 'sortidos',
    'grade (10, 12, 15) por modelo e cor': 'grade',
    'grade (acima de 12 por grade)': 'grade',
}

# Mapa UF
UF_MAP = {
    'acre': 'AC', 'alagoas': 'AL', 'amapá': 'AP', 'amazonas': 'AM',
    'bahia': 'BA', 'ceará': 'CE', 'distrito federal': 'DF',
    'espírito santo': 'ES', 'espirito santo': 'ES', 'goiás': 'GO', 'goias': 'GO',
    'maranhão': 'MA', 'mato grosso': 'MT', 'mato grosso do sul': 'MS',
    'minas gerais': 'MG', 'pará': 'PA', 'paraíba': 'PB', 'paraiba': 'PB',
    'paraná': 'PR', 'parana': 'PR', 'pernambuco': 'PE', 'piauí': 'PI',
    'rio de janeiro': 'RJ', 'rio grande do norte': 'RN',
    'rio grande do sul': 'RS', 'rondônia': 'RO', 'roraima': 'RR',
    'santa catarina': 'SC', 'são paulo': 'SP', 'sao paulo': 'SP',
    'sergipe': 'SE', 'tocantins': 'TO',
    'sp': 'SP', 'rj': 'RJ', 'mg': 'MG', 'rs': 'RS', 'pr': 'PR',
    'sc': 'SC', 'ba': 'BA', 'ce': 'CE', 'pe': 'PE', 'pa': 'PA',
    'go': 'GO', 'df': 'DF', 'mt': 'MT', 'ms': 'MS', 'ma': 'MA',
    'es': 'ES', 'am': 'AM', 'rn': 'RN', 'pb': 'PB', 'al': 'AL',
    'se': 'SE', 'pi': 'PI', 'ro': 'RO', 'to': 'TO', 'ac': 'AC',
    'ap': 'AP', 'rr': 'RR',
}


def limpar_telefone(raw):
    """Limpa telefone do formato do ClickUp: =+55 16 99783 6472"""
    if not raw:
        return ''
    s = str(raw)
    # Remove =, +, espaços
    digits = re.sub(r'[^0-9]', '', s)
    if digits.startswith('55') and len(digits) >= 12:
        return digits  # Já com 55
    if len(digits) in (10, 11):
        return '55' + digits
    return digits


def limpar_cpf(raw):
    if not raw:
        return ''
    s = str(raw).replace('.0', '').strip()
    digits = re.sub(r'[^0-9]', '', s)
    return digits[:11] if digits else ''


def limpar_cnpj(raw):
    if not raw:
        return ''
    s = str(raw).replace('.0', '').strip()
    digits = re.sub(r'[^0-9]', '', s)
    return digits[:14] if digits else ''


def normalizar_uf(raw):
    if not raw:
        return ''
    s = str(raw).strip().lower()
    return UF_MAP.get(s, s.upper()[:2])


class Command(BaseCommand):
    help = 'Importa leads de atacado do Excel (ClickUp)'

    def add_arguments(self, parser):
        parser.add_argument('arquivo', type=str, help='Caminho do arquivo .xlsx')
        parser.add_argument('--empresa', type=str, default='tarragona', help='Slug da empresa')
        parser.add_argument('--dry-run', action='store_true', help='Apenas simular')

    def handle(self, *args, **options):
        import openpyxl

        arquivo = options['arquivo']
        empresa_slug = options['empresa']
        dry_run = options['dry_run']

        try:
            empresa = Empresa.objects.get(slug=empresa_slug)
        except Empresa.DoesNotExist:
            self.stderr.write(f'Empresa "{empresa_slug}" não encontrada')
            return

        wb = openpyxl.load_workbook(arquivo)
        ws = wb.active

        # Colunas do Excel (baseado na análise):
        # 0: id, 1: Nome, 2: WhatsApp, 3: Status negocio, 4: Nome empresa
        # 5: data criada, 7: cpf/cnpj, 8: email, 9: cpf, 10: instagram
        # 11: site, 16: Cidade, 17: Estado, 19: Plano, 20: Private Label
        # 23: Ramo/Nicho, 24: Status do CRM

        importados = 0
        duplicados = 0
        ignorados = 0
        erros = 0

        for row_num, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            nome = str(row[1]).strip() if row[1] else ''

            if not nome or nome.lower() in ('none', '', 'virou cliente', 'conversando',
                                              'to do', 'curioso'):
                ignorados += 1
                continue

            whatsapp = limpar_telefone(row[2])
            status_negocio = str(row[3]).strip().lower() if row[3] else ''
            nome_empresa = str(row[4]).strip() if row[4] else ''
            data_criada = row[5]
            cnpj = limpar_cnpj(row[7])
            email = str(row[8]).strip() if row[8] else ''
            cpf = limpar_cpf(row[9])
            instagram = str(row[10]).strip() if row[10] else ''
            site = str(row[11]).strip() if row[11] else ''
            cidade = str(row[16]).strip() if row[16] else ''
            estado_raw = str(row[17]).strip() if row[17] else ''
            plano_raw = str(row[19]).strip().lower() if row[19] else ''
            private_label_raw = str(row[20]).strip().lower() if row[20] else ''
            nicho = str(row[23]).strip() if row[23] else ''
            status_crm = str(row[24]).strip().lower() if row[24] else 'novo'

            # Limpar valores None
            for var_name in ['email', 'instagram', 'site', 'nome_empresa', 'nicho', 'cidade']:
                val = locals()[var_name]
                if val.lower() == 'none':
                    locals()[var_name] = ''

            if email.lower() == 'none':
                email = ''
            if instagram.lower() == 'none':
                instagram = ''
            if site.lower() == 'none':
                site = ''
            if nome_empresa.lower() == 'none':
                nome_empresa = ''
            if nicho.lower() == 'none':
                nicho = ''
            if cidade.lower() == 'none':
                cidade = ''

            # Verificar duplicata
            if whatsapp:
                exists = LeadAtacado.objects.filter(empresa=empresa, whatsapp=whatsapp).exists()
            elif email:
                exists = LeadAtacado.objects.filter(empresa=empresa, email=email).exists()
            else:
                exists = LeadAtacado.objects.filter(
                    empresa=empresa, nome_completo=nome
                ).exists()

            if exists:
                duplicados += 1
                continue

            # Mapear valores
            status = STATUS_MAP.get(status_crm, 'novo')
            status_empresa = STATUS_EMPRESA_MAP.get(status_negocio, '')
            plano = PLANO_MAP.get(plano_raw, '')
            estado = normalizar_uf(estado_raw)

            private_label = ''
            if private_label_raw == 'sim':
                private_label = 'sim'
            elif private_label_raw in ('não', 'nao'):
                private_label = 'nao'
            elif private_label_raw:
                private_label = 'talvez'

            if dry_run:
                self.stdout.write(
                    f'  [{status}] {nome} | {whatsapp} | {cidade}/{estado} | '
                    f'{status_empresa} | {nome_empresa}'
                )
                importados += 1
                continue

            try:
                lead = LeadAtacado(
                    empresa=empresa,
                    nome_completo=nome,
                    cpf=cpf,
                    email=email,
                    whatsapp=whatsapp,
                    cidade=cidade,
                    estado=estado,
                    status_empresa=status_empresa,
                    nome_empresa=nome_empresa,
                    cnpj=cnpj,
                    nicho_empresarial=nicho,
                    instagram=instagram,
                    site_vendas=site,
                    plano_interesse=plano,
                    private_label=private_label,
                    status=status,
                    origem='importacao',
                )
                lead.save()

                # Atualizar created_at se temos data original
                if isinstance(data_criada, datetime):
                    LeadAtacado.objects.filter(pk=lead.pk).update(
                        created_at=timezone.make_aware(data_criada)
                        if timezone.is_naive(data_criada)
                        else data_criada
                    )

                importados += 1

            except Exception as e:
                erros += 1
                self.stderr.write(f'  Erro linha {row_num} ({nome}): {e}')

        prefix = '[DRY RUN] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'\n{prefix}Importação concluída:'
            f'\n  Importados: {importados}'
            f'\n  Duplicados: {duplicados}'
            f'\n  Ignorados: {ignorados}'
            f'\n  Erros: {erros}'
        ))
