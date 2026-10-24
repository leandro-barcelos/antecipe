import csv


def carregar_situacoes_cadastrais(file_path):
    """Lê a base cadastral indexada pelo documento completo do sacado."""
    with open(file_path, "r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file, delimiter=";")
        if not {"DOC", "SITUACAO_CADASTRAL"}.issubset(reader.fieldnames or []):
            raise RuntimeError(
                "A base cadastral deve conter as colunas DOC e SITUACAO_CADASTRAL"
            )
        return {
            row["DOC"].strip(): (row["SITUACAO_CADASTRAL"] or "").strip()
            for row in reader
            if row["DOC"] and row["DOC"].strip()
        }
