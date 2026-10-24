"""Whitelisted, parameterized SQL predicates for receivables eligibility."""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_CEILING, localcontext
import re


MAX_CENTS = 2**63 - 1
MAX_MONEY = Decimal('92233720368547758.07')


def normalizar_cnpj(documento):
    return re.sub(r'\D', '', documento)


def normalizar_nome(nome):
    return ' '.join(nome.split()).casefold()


def normalizar_data(valor):
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return datetime.strptime(valor, '%d/%m/%Y').date()


@dataclass(frozen=True)
class SQLRule:
    codigo: str
    ordem: int
    predicado: str
    parametros: tuple = ()


def _cnpj(parametros, ordem, referencia):
    return 'r.cnpj_sacado_valido = 1', ()


def _lista(coluna, valores):
    if not valores:
        return '0', ()
    return f"{coluna} IN ({','.join('?' for _ in valores)})", tuple(valores)


def _situacao(parametros, ordem, referencia):
    condition, values = _lista('c.situacao', [s.strip().upper() for s in parametros['situacoes_aceitas']])
    return f'EXISTS (SELECT 1 FROM cadastro c WHERE c.cnpj=r.doc_sacado AND {condition})', values


def _tipo(parametros, ordem, referencia):
    return _lista('r.tipo', parametros['tipos_aceitos'])


def _minimo(parametros, ordem, referencia):
    amount = Decimal(str(parametros['valor_minimo']))
    if amount > MAX_MONEY:
        return '0', ()
    with localcontext() as context:
        context.prec = max(28, len(amount.as_tuple().digits) + 4)
        cents = int((amount * 100).to_integral_value(rounding=ROUND_CEILING))
    return 'r.nominal >= ?', (cents,)


def _nao_vencida(parametros, ordem, referencia):
    return 'r.vencimento >= ?', (referencia.toordinal(),)


def _prazo_maximo(parametros, ordem, referencia):
    return 'r.prazo BETWEEN 0 AND ?', (min(parametros['prazo_maximo_dias'], date.max.toordinal()),)


def _prazo_minimo(parametros, ordem, referencia):
    return 'r.prazo >= ?', (min(parametros['prazo_minimo_dias'], date.max.toordinal()),)


def coluna_concentracao(codigo, parametros):
    entidade = 'sacado' if codigo == 'CONCENTRACAO_MAXIMA_SACADO' else 'cedente'
    coluna = f'raiz_{entidade}' if parametros.get('agrupamento', 'CNPJ') == 'RAIZ_CNPJ' else f'doc_{entidade}'
    return entidade, coluna


def _concentracao(codigo, parametros, ordem):
    entidade, coluna = coluna_concentracao(codigo, parametros)
    return (
        f'length(r.doc_{entidade})=14 AND EXISTS ('
        f'SELECT 1 FROM grupos g WHERE g.ordem=? AND g.documento=r.{coluna} AND g.aprovado=1)',
        (ordem,),
    )


RULES = {
    'CNPJ_SACADO_VALIDO': _cnpj,
    'SITUACAO_CADASTRAL_SACADO': _situacao,
    'TIPO_RECEBIVEL': _tipo,
    'VALOR_MINIMO': _minimo,
    'NAO_VENCIDA': _nao_vencida,
    'PRAZO_MAXIMO': _prazo_maximo,
    'PRAZO_MINIMO': _prazo_minimo,
    'CONCENTRACAO_MAXIMA_SACADO': None,
    'CONCENTRACAO_MAXIMA_CEDENTE': None,
}


def compilar_regras(config, referencia):
    rules = [SQLRule('FUNDO_VALIDO', 0, 'r.pertence_fundo=1')]
    for ordem, regra in enumerate(config['validadores'], start=1):
        if not regra['ativo']:
            continue
        codigo = regra['codigo']
        if codigo.startswith('CONCENTRACAO_MAXIMA_'):
            sql, params = _concentracao(codigo, regra['parametros'], ordem)
        else:
            sql, params = RULES[codigo](regra['parametros'], ordem, referencia)
        rules.append(SQLRule(codigo, ordem, sql, params))
    return rules
