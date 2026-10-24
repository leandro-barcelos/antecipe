
import csv
import io
import os
import zipfile

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional


REQUIRED_COLUMNS = [
    "NOME_FUNDO",
    "DOC_FUNDO",
    "NOME_CEDENTE",
    "DOC_CEDENTE",
    "NOME_SACADO",
    "DOC_SACADO",
    "NU_DOCUMENTO",
    "TIPO_RECEBIVEL",
    "VALOR_NOMINAL",
    "DATA_VENCIMENTO_ORIGINAL",
    "DATA_AQUISICAO",
]


@dataclass
class ParseResult:
    row_number: int
    data: Optional[dict]
    errors: list[str]
    document_id: str = ""
    duplicate: bool = False


def parse_money(value: str) -> Decimal:
    value = value.strip().replace(".", "").replace(",", ".")

    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ValueError("Valor nominal inválido")

    if not amount.is_finite() or amount < 0:
        raise ValueError("Valor nominal inválido")

    return amount


def parse_date(value: str) -> date:
    try:
        return datetime.strptime(
            value.strip(), "%d/%m/%Y"
        ).date()
    except ValueError:
        raise ValueError("Data inválida (DD/MM/AAAA)")


def parse_row(item: tuple[int, dict]) -> ParseResult:
    row_number, row = item
    errors = []
    data = {}

    for field in REQUIRED_COLUMNS:
        data[field] = (row.get(field) or "").strip()

    try:
        data["VALOR_NOMINAL"] = parse_money(
            data["VALOR_NOMINAL"]
        )
    except ValueError as exc:
        errors.append(str(exc))

    for field in [
        "DATA_VENCIMENTO_ORIGINAL",
        "DATA_AQUISICAO",
    ]:
        try:
            data[field] = parse_date(data[field])
        except ValueError as exc:
            errors.append(f"{field}: {exc}")

    return ParseResult(
        row_number=row_number,
        data=data if not errors else None,
        errors=errors,
        document_id=data["NU_DOCUMENTO"],
    )


def _process_chunk(chunk):
    return [parse_row(item) for item in chunk]


def _read_chunks(reader, chunk_size):
    chunk = []

    for row_number, row in enumerate(reader, start=2):
        chunk.append((row_number, row))

        if len(chunk) >= chunk_size:
            yield chunk
            chunk = []

    if chunk:
        yield chunk


def _parse_stream(
    stream,
    parallel=False,
    workers=None,
    chunk_size=5000,
):
    reader = csv.DictReader(stream, delimiter=";")

    if reader.fieldnames is None:
        raise ValueError("CSV vazio ou sem cabeçalho")

    missing = set(REQUIRED_COLUMNS) - set(reader.fieldnames)

    if missing:
        raise ValueError(
            f"Colunas obrigatórias ausentes: {sorted(missing)}"
        )

    chunks = _read_chunks(reader, chunk_size)

    if parallel:
        worker_count = workers or min(os.cpu_count() or 1, 4)

        with ProcessPoolExecutor(
            max_workers=worker_count
        ) as executor:
            for results in executor.map(
                _process_chunk, chunks
            ):
                yield from results
    else:
        for chunk in chunks:
            yield from _process_chunk(chunk)


def parse_csv(
    file_path,
    parallel=False,
    workers=None,
    chunk_size=5000,
):
    """
    Parseia CSV ou ZIP contendo estoque_antecipe.csv.

    Retorna um iterador de ParseResult.
    """

    path = Path(file_path)

    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            csv_files = [
                name for name in archive.namelist()
                if name.lower().endswith(".csv")
                and not name.startswith("__MACOSX/")
            ]

            if len(csv_files) != 1:
                raise ValueError(
                    "O ZIP deve conter exatamente um CSV"
                )

            with archive.open(csv_files[0]) as binary, io.TextIOWrapper(
                binary, encoding="utf-8-sig",
                newline=""
            ) as stream:
                yield from _parse_stream(
                    stream, parallel, workers, chunk_size
                )

    else:
        with open(
            path, "r", encoding="utf-8-sig", newline=""
        ) as stream:
            yield from _parse_stream(
                stream, parallel, workers, chunk_size
            )
