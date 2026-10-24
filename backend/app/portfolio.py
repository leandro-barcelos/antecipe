"""Decimal pricing of SQL-approved titles and SQL portfolio summaries."""
from datetime import date
from decimal import Decimal, InvalidOperation

from .database import DEFAULT_CHUNK_SIZE, format_cents
from .pricing import Precificador


def precificar_aprovados(database, config, *, chunk_size=DEFAULT_CHUNK_SIZE):
    connection = database.connection
    pricer = Precificador(config['precificacao'])
    last_line = 0
    with connection:
        while True:
            batch = connection.execute(
                'SELECT linha,nominal,aquisicao,vencimento FROM recebiveis '
                'WHERE aprovado=1 AND linha>? ORDER BY linha LIMIT ?',
                (last_line, chunk_size),
            ).fetchall()
            if not batch:
                break
            prices, failures = [], []
            for row in batch:
                try:
                    price = pricer.calcular({
                        'VALOR_NOMINAL': Decimal(row['nominal']).scaleb(-2),
                        'DATA_AQUISICAO': date.fromordinal(row['aquisicao']),
                        'DATA_VENCIMENTO_ORIGINAL': date.fromordinal(row['vencimento']),
                    })
                except (ValueError, InvalidOperation):
                    failures.append((row['linha'],))
                else:
                    prices.append((row['linha'], int(price.valor_nominal * 100),
                                   int(price.desconto * 100), int(price.valor_liquido * 100), price.prazo_dias))
            connection.executemany('INSERT INTO precos VALUES (?,?,?,?,?)', prices)
            connection.executemany("INSERT INTO falhas VALUES (?,2147483647,'PRECIFICACAO_INVALIDA')", failures)
            connection.executemany('UPDATE recebiveis SET aprovado=0 WHERE linha=?', failures)
            last_line = batch[-1]['linha']


def resumo(database):
    connection = database.connection
    counts = connection.execute('''SELECT COUNT(*) AS linhas,
        COALESCE(SUM(aprovado),0) AS aprovados,
        COALESCE(SUM(duplicado_de IS NOT NULL),0) AS duplicatas
        FROM recebiveis''').fetchone()
    money = connection.execute('''SELECT COALESCE(SUM(p.nominal),0) AS nominal,
        COALESCE(SUM(p.liquido),0) AS liquido
        FROM precos p JOIN recebiveis r ON r.linha=p.linha WHERE r.aprovado=1''').fetchone()
    return {
        'linhas': counts['linhas'], 'aprovados': counts['aprovados'],
        'barrados': counts['linhas'] - counts['aprovados'],
        'duplicatas_excluidas': counts['duplicatas'],
        'valor_nominal': format_cents(money['nominal']),
        'valor_liquido': format_cents(money['liquido']),
    }
