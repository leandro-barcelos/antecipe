"""Execute eligibility predicates and concentration aggregates in SQLite."""
from datetime import datetime
from zoneinfo import ZoneInfo

from .database import BASE, DEFAULT_CHUNK_SIZE
from .validator import coluna_concentracao, compilar_regras


def data_operacao():
    return datetime.now(ZoneInfo('America/Sao_Paulo')).date()


def validar_base(database, config, *, data_referencia=None):
    reference = data_referencia if data_referencia is not None else data_operacao()
    connection = database.connection
    rules = compilar_regras(config, reference)
    concentration = [
        (order, rule) for order, rule in enumerate(config['validadores'], start=1)
        if rule['ativo'] and rule['codigo'].startswith('CONCENTRACAO_MAXIMA_')
    ]
    with connection:
        if concentration:
            for order, rule in concentration:
                entity, column = coluna_concentracao(rule['codigo'], rule['parametros'])
                connection.execute(f'''WITH fundos AS MATERIALIZED (
                    SELECT r.doc_fundo,SUM(r.nominal) total FROM recebiveis r
                    WHERE {BASE} GROUP BY r.doc_fundo
                ) INSERT INTO grupos
                    SELECT ?,r.doc_fundo,r.{column},SUM(r.nominal),
                        concentracao_exata(SUM(r.nominal),f.total,?)
                    FROM recebiveis r JOIN fundos f ON f.doc_fundo=r.doc_fundo
                    WHERE {BASE} AND length(r.doc_{entity})=14
                    GROUP BY r.doc_fundo,r.{column}''',
                    (order, str(rule['parametros']['percentual_maximo'])),
                )
        for rule in rules:
            connection.execute(
                f'''INSERT INTO falhas SELECT r.linha,?,? FROM recebiveis r
                    WHERE r.erros IS NULL AND r.duplicado_de IS NULL
                    AND COALESCE(({rule.predicado}),0)=0''',
                (rule.ordem, rule.codigo, *rule.parametros),
            )
        connection.execute('''UPDATE recebiveis AS r SET aprovado=NOT EXISTS (
            SELECT 1 FROM falhas f WHERE f.linha=r.linha)''')
