import copy
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

from backend.app.config import carregar_configuracao, validar_configuracao
from backend.app.csv_parser import parse_row
from backend.app.database import ReceivablesDatabase
from backend.app.situacao_cadastral import carregar_situacoes_cadastrais
from backend.app.validation import validar_base
from backend.app.validator import compilar_regras


CONFIG_PATH = Path(__file__).resolve().parents[1] / 'data/validadores_antecipe.json'
FUNDO = {'nome': 'ANTECIPE FIDC', 'cnpj': '92.234.400/0001-80'}
CNPJ = '04.252.011/0001-10'
FILIAL = '04.252.011/0002-00'
OUTRO_CNPJ = '11.222.333/0001-81'
HOJE = date(2026, 10, 24)


def titulo(**overrides):
    return {
        'NOME_FUNDO': FUNDO['nome'], 'DOC_FUNDO': FUNDO['cnpj'],
        'DOC_SACADO': CNPJ, 'DOC_CEDENTE': OUTRO_CNPJ,
        'NU_DOCUMENTO': '0001', 'VALOR_NOMINAL': '100,00', 'TIPO_RECEBIVEL': 'Duplicata',
        'DATA_AQUISICAO': '27/04/2026', 'DATA_VENCIMENTO_ORIGINAL': '24/10/2026', **overrides,
    }


def config_regra(codigo, parametros=None, ativo=True):
    return {'fundo': FUNDO, 'validadores': [{'codigo': codigo, 'ativo': ativo, 'parametros': parametros or {}}]}


def avaliar(config, rows, statuses=None):
    validar_configuracao(config)
    with ReceivablesDatabase(':memory:') as database:
        database.import_rows((parse_row((i + 2, row)) for i, row in enumerate(rows)), config['fundo'], chunk_size=2)
        database.import_statuses(statuses or {})
        validar_base(database, config, data_referencia=HOJE)
        return list(database.iter_records(chunk_size=2))


class ConfiguracaoTests(unittest.TestCase):
    def test_carrega_configuracao_validada(self):
        config = carregar_configuracao(CONFIG_PATH)
        rules = compilar_regras(config, HOJE)
        expected = ['FUNDO_VALIDO'] + [r['codigo'] for r in config['validadores'] if r['ativo']]
        self.assertEqual([r.codigo for r in rules], expected)

    def test_rejeita_codigo_ativo_desconhecido(self):
        with self.assertRaisesRegex(ValueError, 'Validador não suportado'):
            validar_configuracao(config_regra('DESCONHECIDO'))
        result = avaliar(config_regra('DESCONHECIDO', ativo=False), [titulo()])
        self.assertEqual(result[0]['status'], 'APROVADO')

    def test_rejeita_parametros_invalidos(self):
        for code in ('CONCENTRACAO_MAXIMA_SACADO', 'CONCENTRACAO_MAXIMA_CEDENTE'):
            for maximum, grouping in ((-1,'CNPJ'),(101,'CNPJ'),(10,'NOME'),('NaN','CNPJ'),('Infinity','CNPJ')):
                with self.subTest(code=code, maximum=maximum, grouping=grouping):
                    with self.assertRaises(ValueError):
                        validar_configuracao(config_regra(code, {'percentual_maximo': maximum, 'agrupamento': grouping}))

    def test_rejeita_fundo_invalido(self):
        for fund in (None, [], {}, {'nome':' '}, {'nome':'ANTECIPE FIDC'}, {'nome':'ANTECIPE FIDC','cnpj':92234400000180}, {'nome':'ANTECIPE FIDC','cnpj':'92234400000181'}):
            with self.subTest(fund=fund), self.assertRaises(ValueError):
                validar_configuracao({'fundo': fund, 'validadores': []})
        with self.assertRaises(ValueError):
            validar_configuracao({'validadores': []})

    def test_aceita_fundo_sem_mascara_e_regras_desativadas(self):
        config = {'fundo': {'nome': ' antecipe  fidc ', 'cnpj': '92234400000180'}, 'validadores': []}
        self.assertEqual(avaliar(config, [titulo()])[0]['status'], 'APROVADO')


class SQLRulesTests(unittest.TestCase):
    def test_todas_regras_ativas(self):
        config = carregar_configuracao(CONFIG_PATH)
        result = avaliar(config, [titulo(), titulo(NU_DOCUMENTO='0002', DOC_SACADO=OUTRO_CNPJ, VALOR_NOMINAL='900,00')], {CNPJ:'ATIVA', OUTRO_CNPJ:'ATIVA'})
        self.assertEqual(result[0]['status'], 'APROVADO')
        self.assertEqual(result[1]['barrado_por'], ['CONCENTRACAO_MAXIMA_SACADO'])

    def test_cnpj_sacado_valido_invalido_e_ausente(self):
        config = config_regra('CNPJ_SACADO_VALIDO')
        for document, expected in ((CNPJ,'APROVADO'),('04.252.011/0001-11','BARRADO'),('','BARRADO')):
            with self.subTest(document=document):
                self.assertEqual(avaliar(config, [titulo(DOC_SACADO=document)])[0]['status'], expected)

    def test_situacao_completa_normalizada_e_nao_aceita(self):
        config = config_regra('SITUACAO_CADASTRAL_SACADO', {'situacoes_aceitas':['ATIVA']})
        for status, expected in ((' ativa ','APROVADO'),('BAIXADA','BARRADO'),(None,'BARRADO'),('','BARRADO')):
            with self.subTest(status=status):
                self.assertEqual(avaliar(config, [titulo()], {'04252011000110':status})[0]['status'], expected)
        self.assertEqual(avaliar(config, [titulo(DOC_SACADO=FILIAL)], {CNPJ:'ATIVA'})[0]['status'], 'BARRADO')

    def test_listas_vazias_reprovam_sem_sql_invalido(self):
        for code, field in (('SITUACAO_CADASTRAL_SACADO','situacoes_aceitas'),('TIPO_RECEBIVEL','tipos_aceitos')):
            with self.subTest(code=code):
                result = avaliar(config_regra(code, {field:[]}), [titulo()], {CNPJ:'ATIVA'})
                self.assertEqual(result[0]['barrado_por'], [code])

    def test_parametros_sql_sao_dados(self):
        value = "Duplicata'); DROP TABLE recebiveis; --"
        config = config_regra('TIPO_RECEBIVEL', {'tipos_aceitos':[value]})
        self.assertEqual(avaliar(config, [titulo(TIPO_RECEBIVEL=value)])[0]['status'], 'APROVADO')
        self.assertEqual(avaliar(config, [titulo()])[0]['status'], 'BARRADO')

    def test_valor_minimo_usa_teto_exato_sem_real(self):
        for minimum, expected in (('100','APROVADO'),('100.0000000000000000000000000001','BARRADO'),('1e1000','BARRADO')):
            with self.subTest(minimum=minimum):
                result = avaliar(config_regra('VALOR_MINIMO', {'valor_minimo':minimum}), [titulo()])
                self.assertEqual(result[0]['status'], expected)

    def test_limites_de_datas(self):
        cases = (
            ('NAO_VENCIDA',{},'24/10/2026','APROVADO'), ('NAO_VENCIDA',{},'23/10/2026','BARRADO'),
            ('PRAZO_MAXIMO',{'prazo_maximo_dias':180},'24/10/2026','APROVADO'),
            ('PRAZO_MAXIMO',{'prazo_maximo_dias':180},'25/10/2026','BARRADO'),
            ('PRAZO_MAXIMO',{'prazo_maximo_dias':180},'26/04/2026','BARRADO'),
            ('PRAZO_MINIMO',{'prazo_minimo_dias':180},'24/10/2026','APROVADO'),
            ('PRAZO_MINIMO',{'prazo_minimo_dias':181},'24/10/2026','BARRADO'),
            ('PRAZO_MAXIMO',{'prazo_maximo_dias':10**100},'24/10/2026','APROVADO'),
            ('PRAZO_MINIMO',{'prazo_minimo_dias':10**100},'24/10/2026','BARRADO'),
        )
        for code, parameters, due, expected in cases:
            with self.subTest(code=code, due=due, parameters=parameters):
                result = avaliar(config_regra(code, parameters), [titulo(DATA_VENCIMENTO_ORIGINAL=due)])
                self.assertEqual(result[0]['status'], expected)

    def test_falhas_na_ordem_e_pendencias_nao_interrompem(self):
        config = carregar_configuracao(CONFIG_PATH)
        result = avaliar(config, [titulo(VALOR_NOMINAL='50,00', TIPO_RECEBIVEL='Outro')])
        self.assertEqual(result[0]['barrado_por'], ['SITUACAO_CADASTRAL_SACADO','TIPO_RECEBIVEL','VALOR_MINIMO','CONCENTRACAO_MAXIMA_SACADO'])

    def test_regras_inativas_nao_filtram_e_codigos_repetidos_preservam_ordem(self):
        config = config_regra('VALOR_MINIMO', {'valor_minimo':200})
        config['validadores'].append(copy.deepcopy(config['validadores'][0]))
        self.assertEqual(avaliar(config,[titulo()])[0]['barrado_por'], ['VALOR_MINIMO','VALOR_MINIMO'])
        for rule in config['validadores']:
            rule['ativo'] = False
        self.assertEqual(avaliar(config,[titulo()])[0]['status'], 'APROVADO')


class ConcentracaoTests(unittest.TestCase):
    def rows(self):
        return [titulo(VALOR_NOMINAL='50,00'), titulo(NU_DOCUMENTO='2',DOC_SACADO=FILIAL,VALOR_NOMINAL='50,00'),
                titulo(NU_DOCUMENTO='3',DOC_SACADO=OUTRO_CNPJ,DOC_CEDENTE=CNPJ,VALOR_NOMINAL='900,00')]

    def test_agrupamento_raiz_soma_filiais_e_aceita_limite_exato(self):
        config = config_regra('CONCENTRACAO_MAXIMA_SACADO', {'percentual_maximo':10,'agrupamento':'RAIZ_CNPJ'})
        self.assertEqual([r['status'] for r in avaliar(config,self.rows())], ['APROVADO','APROVADO','BARRADO'])

    def test_quatro_combinacoes_de_entidade_e_agrupamento(self):
        for entity in ('SACADO','CEDENTE'):
            for grouping in ('CNPJ','RAIZ_CNPJ'):
                with self.subTest(entity=entity, grouping=grouping):
                    config = config_regra('CONCENTRACAO_MAXIMA_'+entity, {'percentual_maximo':8,'agrupamento':grouping})
                    result = avaliar(config,self.rows())
                    expected = 'APROVADO' if entity=='SACADO' and grouping=='CNPJ' else 'BARRADO'
                    self.assertEqual(result[0]['status'],expected)

    def test_cedente_usa_cnpj_como_padrao(self):
        config = config_regra('CONCENTRACAO_MAXIMA_CEDENTE', {'percentual_maximo':10})
        self.assertEqual([r['status'] for r in avaliar(config,self.rows())], ['APROVADO','APROVADO','BARRADO'])

    def test_nao_arredonda_excesso_e_nao_converte_produtos_para_real(self):
        cases = (('100,01','899,99',10), ('45035996273704,97','45035996273704,96',50))
        for first, second, limit in cases:
            with self.subTest(first=first):
                rows=[titulo(VALOR_NOMINAL=first),titulo(NU_DOCUMENTO='2',DOC_SACADO=OUTRO_CNPJ,VALOR_NOMINAL=second)]
                result=avaliar(config_regra('CONCENTRACAO_MAXIMA_SACADO', {'percentual_maximo':limit}),rows)
                self.assertEqual(result[0]['status'],'BARRADO')

    def test_base_zero_e_documento_incompleto_ficam_barrados(self):
        config=config_regra('CONCENTRACAO_MAXIMA_SACADO', {'percentual_maximo':100})
        for row in (titulo(VALOR_NOMINAL='0,00'),titulo(DOC_SACADO='123')):
            with self.subTest(row=row):
                self.assertEqual(avaliar(config,[row])[0]['status'],'BARRADO')


class CadastroCSVTests(unittest.TestCase):
    def test_bom_normalizacao_e_situacao_vazia(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'situacoes.csv'
            path.write_text(f'\ufeffDOC;SITUACAO_CADASTRAL\n{CNPJ}; ativa \n{OUTRO_CNPJ};\n',encoding='utf-8')
            statuses=carregar_situacoes_cadastrais(path)
        config=config_regra('SITUACAO_CADASTRAL_SACADO',{'situacoes_aceitas':['ATIVA']})
        result=avaliar(config,[titulo(DOC_SACADO='04252011000110'),titulo(NU_DOCUMENTO='2',DOC_SACADO=OUTRO_CNPJ)],statuses)
        self.assertEqual([r['status'] for r in result],['APROVADO','BARRADO'])

    def test_colunas_obrigatorias(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'situacoes.csv'
            path.write_text('CNPJ;STATUS\n',encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError,'DOC e SITUACAO_CADASTRAL'):
                carregar_situacoes_cadastrais(path)
