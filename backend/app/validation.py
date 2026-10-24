import json
import os
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from itertools import islice
from multiprocessing import get_context

from .pricing import Precificador
from .validator import Validator


DEFAULT_CHUNK_SIZE = 5000
_worker_validator = None
_worker_pricer = None


@dataclass
class ValidatedChunk:
    content: str
    total: int
    valid: int
    approved: int
    duplicates: int = 0
    valor_nominal: Decimal = Decimal("0.00")
    desconto: Decimal = Decimal("0.00")
    valor_liquido: Decimal = Decimal("0.00")


def _initialize_worker(config, contexto, precificar=False):
    global _worker_validator, _worker_pricer
    _worker_validator = Validator(config, contexto)
    _worker_pricer = Precificador(config["precificacao"]) if precificar else None


def _validate_chunk(chunk, validator, pricer=None):
    serialized = []
    valid = approved = duplicates = 0
    nominal = desconto = liquido = Decimal("0.00")
    for result in chunk:
        record = {
            "linha": result.row_number,
            "id": result.document_id or (result.data or {}).get("NU_DOCUMENTO", ""),
            "status": "BARRADO",
        }
        if not result.errors:
            valid += 1
        if result.errors:
            record["barrado_por"] = ["ERRO_CSV"]
        elif result.duplicate:
            duplicates += 1
            record["barrado_por"] = ["DUPLICADO"]
        else:
            validation = validator.executar(result.data)
            if validation["aprovado"]:
                record["status"] = "APROVADO"
                if pricer is not None:
                    try:
                        price = pricer.calcular(result.data)
                    except (ValueError, InvalidOperation):
                        record["status"] = "BARRADO"
                        record["barrado_por"] = ["PRECIFICACAO_INVALIDA"]
                    else:
                        record.update(price.como_dict())
                        nominal += price.valor_nominal
                        desconto += price.desconto
                        liquido += price.valor_liquido
            else:
                record["barrado_por"] = [
                    rule["codigo"]
                    for rule in validation["resultados"]
                    if rule["aprovado"] is not True
                ]
        approved += record["status"] == "APROVADO"
        serialized.append(
            json.dumps(
                record,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
        )
    return ValidatedChunk(
        content=",".join(serialized), total=len(chunk), valid=valid, approved=approved,
        duplicates=duplicates, valor_nominal=nominal, desconto=desconto, valor_liquido=liquido,
    )


def _process_chunk(chunk):
    return _validate_chunk(chunk, _worker_validator, _worker_pricer)


def _chunks(rows, chunk_size):
    while chunk := list(islice(rows, chunk_size)):
        yield chunk


def iter_validated_chunks(
    rows, config, contexto, *, chunk_size=DEFAULT_CHUNK_SIZE, workers=None, precificar=False
):
    """Valida blocos em ordem, com no máximo um bloco pendente por processo."""
    worker_count = workers if workers is not None else min(os.cpu_count() or 1, 4)
    if chunk_size < 1 or worker_count < 1:
        raise ValueError("chunk_size e workers devem ser maiores que zero")

    chunks = _chunks(iter(rows), chunk_size)
    first = next(chunks, None)
    if not first:
        return

    if worker_count == 1 or len(first) < chunk_size:
        validator = Validator(config, contexto)
        pricer = Precificador(config["precificacao"]) if precificar else None
        yield _validate_chunk(first, validator, pricer)
        del first
        for chunk in chunks:
            yield _validate_chunk(chunk, validator, pricer)
        return

    with ProcessPoolExecutor(
        max_workers=worker_count,
        mp_context=get_context("spawn"),
        initializer=_initialize_worker,
        initargs=(config, contexto, precificar),
    ) as executor:
        pending = deque([executor.submit(_process_chunk, first)])
        del first
        try:
            for chunk in chunks:
                pending.append(executor.submit(_process_chunk, chunk))
                if len(pending) >= worker_count:
                    yield pending.popleft().result()
            while pending:
                yield pending.popleft().result()
        finally:
            for future in pending:
                future.cancel()
