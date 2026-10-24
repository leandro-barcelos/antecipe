import json
import os
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from itertools import islice
from multiprocessing import get_context

from fastapi.encoders import jsonable_encoder

from .validator import Validator


DEFAULT_CHUNK_SIZE = 5000
_worker_validator = None


@dataclass
class ValidatedChunk:
    content: str
    total: int
    valid: int
    approved: int


def _initialize_worker(config, contexto):
    global _worker_validator
    _worker_validator = Validator(config, contexto)


def _validate_chunk(chunk, validator):
    serialized = []
    valid = approved = 0
    for result in chunk:
        validation = None
        if not result.errors:
            valid += 1
            validation = validator.executar(result.data)
            approved += validation["aprovado"]
        serialized.append(json.dumps(
            jsonable_encoder({
                "row_number": result.row_number,
                "data": result.data,
                "errors": result.errors,
                "validation": validation,
            }),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ))
    return ValidatedChunk(
        content=",".join(serialized), total=len(chunk), valid=valid, approved=approved
    )


def _process_chunk(chunk):
    return _validate_chunk(chunk, _worker_validator)


def _chunks(rows, chunk_size):
    while chunk := list(islice(rows, chunk_size)):
        yield chunk


def iter_validated_chunks(rows, config, contexto, *, chunk_size=DEFAULT_CHUNK_SIZE, workers=None):
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
        yield _validate_chunk(first, validator)
        del first
        for chunk in chunks:
            yield _validate_chunk(chunk, validator)
        return

    with ProcessPoolExecutor(
        max_workers=worker_count,
        mp_context=get_context("spawn"),
        initializer=_initialize_worker,
        initargs=(config, contexto),
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
