"""A disposable SQLite database for one uploaded receivables file."""
import json
import sqlite3

from validate_docbr import CNPJ

from .validator import normalizar_cnpj, normalizar_nome


DEFAULT_CHUNK_SIZE = 5000
BASE = "r.erros IS NULL AND r.duplicado_de IS NULL AND r.pertence_fundo=1"
SCHEMA = """
CREATE TABLE recebiveis (
    linha INTEGER PRIMARY KEY,
    documento TEXT NOT NULL,
    nome_fundo TEXT, doc_fundo TEXT,
    nome_cedente TEXT, doc_cedente TEXT, raiz_cedente TEXT,
    nome_sacado TEXT, doc_sacado TEXT, raiz_sacado TEXT,
    tipo TEXT, nominal INTEGER, aquisicao INTEGER, vencimento INTEGER, prazo INTEGER,
    cnpj_sacado_valido INTEGER, erros TEXT,
    pertence_fundo INTEGER NOT NULL DEFAULT 0,
    duplicado_de INTEGER,
    aprovado INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE falhas (
    linha INTEGER NOT NULL REFERENCES recebiveis(linha),
    ordem INTEGER NOT NULL, codigo TEXT NOT NULL,
    PRIMARY KEY (linha, ordem)
) WITHOUT ROWID;
CREATE TABLE cadastro (cnpj TEXT PRIMARY KEY, situacao TEXT) WITHOUT ROWID;
CREATE TABLE grupos (
    ordem INTEGER NOT NULL, documento TEXT NOT NULL, total INTEGER NOT NULL,
    aprovado INTEGER NOT NULL, PRIMARY KEY (ordem, documento)
) WITHOUT ROWID;
CREATE TABLE precos (
    linha INTEGER PRIMARY KEY REFERENCES recebiveis(linha),
    nominal INTEGER NOT NULL, desconto INTEGER NOT NULL, liquido INTEGER NOT NULL,
    prazo INTEGER NOT NULL
);
"""


def concentracao_exata(grupo, total, limite):
    from decimal import Decimal

    if grupo is None or total is None or total <= 0:
        return 0
    numerator, denominator = Decimal(limite).as_integer_ratio()
    return int(grupo * 100 * denominator <= total * numerator)


class ReceivablesDatabase:
    def __init__(self, path):
        self.connection = sqlite3.connect(path)
        try:
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys=ON")
            self.connection.execute("PRAGMA temp_store=FILE")
            self.connection.execute("PRAGMA cache_size=-8192")
            self.connection.create_function("concentracao_exata", 3, concentracao_exata, deterministic=True)
            self.connection.executescript(SCHEMA)
        except BaseException:
            self.connection.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.connection.close()

    def import_rows(self, rows, fundo, *, chunk_size=DEFAULT_CHUNK_SIZE):
        if chunk_size < 1:
            raise ValueError("chunk_size deve ser maior que zero")
        cnpj = CNPJ()
        sql = """INSERT INTO recebiveis (
            linha,documento,nome_fundo,doc_fundo,nome_cedente,doc_cedente,raiz_cedente,
            nome_sacado,doc_sacado,raiz_sacado,tipo,nominal,aquisicao,vencimento,prazo,
            cnpj_sacado_valido,erros
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
        batch = []
        with self.connection:
            for result in rows:
                data = result.data or {}
                sacado = normalizar_cnpj(data.get("DOC_SACADO", ""))
                cedente = normalizar_cnpj(data.get("DOC_CEDENTE", ""))
                aquisicao = data.get("DATA_AQUISICAO")
                vencimento = data.get("DATA_VENCIMENTO_ORIGINAL")
                amount = data.get("VALOR_NOMINAL")
                batch.append((
                    result.row_number, result.document_id or data.get("NU_DOCUMENTO", ""),
                    normalizar_nome(data.get("NOME_FUNDO", "")),
                    normalizar_cnpj(data.get("DOC_FUNDO", "")),
                    data.get("NOME_CEDENTE", ""), cedente, cedente[:8] if len(cedente) == 14 else None,
                    data.get("NOME_SACADO", ""), sacado, sacado[:8] if len(sacado) == 14 else None,
                    data.get("TIPO_RECEBIVEL", ""), int(amount * 100) if amount is not None else None,
                    aquisicao.toordinal() if aquisicao else None,
                    vencimento.toordinal() if vencimento else None,
                    (vencimento - aquisicao).days if aquisicao and vencimento else None,
                    int(cnpj.validate(data.get("DOC_SACADO", ""))),
                    json.dumps(result.errors, ensure_ascii=False) if result.errors else None,
                ))
                if len(batch) >= chunk_size:
                    self.connection.executemany(sql, batch)
                    batch.clear()
            if batch:
                self.connection.executemany(sql, batch)
            self.connection.execute(
                "UPDATE recebiveis SET pertence_fundo=COALESCE(doc_fundo=? AND nome_fundo=?,0)",
                (normalizar_cnpj(fundo["cnpj"]), normalizar_nome(fundo["nome"])),
            )
            self.connection.execute("""CREATE INDEX documentos ON recebiveis
                (doc_fundo,doc_cedente,doc_sacado,documento,linha)
                WHERE erros IS NULL AND pertence_fundo=1""")
            self.connection.execute("""WITH primeiros AS MATERIALIZED (
                SELECT linha, MIN(linha) OVER (
                    PARTITION BY doc_fundo,doc_cedente,doc_sacado,documento
                ) AS primeira
                FROM recebiveis WHERE erros IS NULL AND pertence_fundo=1
                    AND doc_fundo<>'' AND doc_cedente<>'' AND doc_sacado<>'' AND documento<>''
            ) UPDATE recebiveis AS r SET duplicado_de=p.primeira
              FROM primeiros p WHERE p.linha=r.linha AND p.primeira<r.linha""")
            self.connection.execute("""INSERT INTO falhas
                SELECT linha,-2,'ERRO_CSV' FROM recebiveis WHERE erros IS NOT NULL""")
            self.connection.execute("""INSERT INTO falhas
                SELECT linha,-1,'DUPLICADO' FROM recebiveis WHERE duplicado_de IS NOT NULL""")

    def import_statuses(self, statuses):
        with self.connection:
            self.connection.executemany(
                "INSERT OR REPLACE INTO cadastro VALUES (?,?)",
                ((normalizar_cnpj(doc), status.strip().upper()) for doc, status in statuses.items() if status is not None),
            )

    def iter_records(self, *, precificar=False, chunk_size=DEFAULT_CHUNK_SIZE):
        cursor = self.connection.execute("""SELECT r.linha,r.documento,r.aprovado,
            p.nominal,p.desconto,p.liquido,p.prazo FROM recebiveis r
            LEFT JOIN precos p ON p.linha=r.linha ORDER BY r.linha""")
        failures = self.connection.execute("SELECT linha,codigo FROM falhas ORDER BY linha,ordem")
        try:
            failure = next(failures, None)
            while batch := cursor.fetchmany(chunk_size):
                for row in batch:
                    record = {"linha": row['linha'], "id": row['documento'], "status": "APROVADO" if row['aprovado'] else "BARRADO"}
                    reasons = []
                    while failure is not None and failure['linha'] == row['linha']:
                        reasons.append(failure['codigo'])
                        failure = next(failures, None)
                    if not row['aprovado']:
                        record['barrado_por'] = reasons
                    elif precificar:
                        record.update({
                            'valor_nominal': format_cents(row['nominal']),
                            'desconto': format_cents(row['desconto']),
                            'valor_liquido': format_cents(row['liquido']),
                            'prazo_dias': row['prazo'],
                        })
                    yield record
        finally:
            cursor.close()
            failures.close()


def format_cents(cents):
    # Integer formatting avoids rounding near SQLite's 64-bit boundary.
    return f"{cents // 100}.{cents % 100:02d}"
