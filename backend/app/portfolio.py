import sqlite3
from contextlib import closing
from dataclasses import dataclass
from decimal import Decimal

from .validator import normalizar_cnpj


def deduplicar(rows, database_path, fundo):
    """Marca repetições globais sem manter todas as chaves em memória."""
    with closing(sqlite3.connect(database_path)) as database, database:
        database.execute("PRAGMA journal_mode=OFF")
        database.execute("PRAGMA synchronous=OFF")
        database.execute(
            "CREATE TABLE IF NOT EXISTS vistos ("
            "fundo TEXT, cedente TEXT, sacado TEXT, documento TEXT, "
            "PRIMARY KEY (fundo, cedente, sacado, documento)) WITHOUT ROWID"
        )
        database.execute("DELETE FROM vistos")
        for row in rows:
            row.duplicate = False
            if not row.errors and fundo.corresponde(row.data):
                data = row.data
                chave = (
                    normalizar_cnpj(data["DOC_FUNDO"]),
                    normalizar_cnpj(data["DOC_CEDENTE"]),
                    normalizar_cnpj(data["DOC_SACADO"]),
                    data["NU_DOCUMENTO"].strip(),
                )
                if all(chave):
                    inserted = database.execute(
                        "INSERT OR IGNORE INTO vistos VALUES (?, ?, ?, ?)", chave
                    )
                    row.duplicate = inserted.rowcount == 0
            yield row


@dataclass
class Carteira:
    linhas: int = 0
    aprovados: int = 0
    duplicatas_excluidas: int = 0
    valor_nominal: Decimal = Decimal("0.00")
    desconto: Decimal = Decimal("0.00")
    valor_liquido: Decimal = Decimal("0.00")

    def adicionar(self, chunk):
        self.linhas += chunk.total
        self.aprovados += chunk.approved
        self.duplicatas_excluidas += chunk.duplicates
        self.valor_nominal += chunk.valor_nominal
        self.desconto += chunk.desconto
        self.valor_liquido += chunk.valor_liquido

    def resumo(self):
        return {
            "linhas": self.linhas,
            "aprovados": self.aprovados,
            "barrados": self.linhas - self.aprovados,
            "duplicatas_excluidas": self.duplicatas_excluidas,
            "valor_nominal": format(self.valor_nominal, ".2f"),
            "desconto": format(self.desconto, ".2f"),
            "valor_liquido": format(self.valor_liquido, ".2f"),
        }
