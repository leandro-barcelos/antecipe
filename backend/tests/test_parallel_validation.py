import json
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from backend.app.config import carregar_configuracao
from backend.app.csv_parser import parse_row
from backend.app.validation import ValidatedChunk, iter_validated_chunks
from backend.app.validator import ContextoValidacao


CONFIG_PATH = Path(__file__).resolve().parents[1] / "data/validadores_antecipe.json"


class ParallelValidationTests(unittest.TestCase):
    def test_parallel_results_match_sequential_with_full_context_and_partial_chunk(self):
        config = carregar_configuracao(CONFIG_PATH)
        amounts = ("100,00", "900,00", "inválido", "50,00", "200,00", "0,00", "100,00")
        rows = [
            parse_row((index + 2, {
                "DOC_SACADO": "04.252.011/0001-10" if index == 0 else "11.222.333/0001-81",
                "DOC_CEDENTE": "11.222.333/0001-81",
                "VALOR_NOMINAL": amount,
                "TIPO_RECEBIVEL": "Duplicata",
                "DATA_AQUISICAO": "27/04/2026",
                "DATA_VENCIMENTO_ORIGINAL": "24/10/2026",
            }))
            for index, amount in enumerate(amounts)
        ]
        contexto = ContextoValidacao(
            (row.data for row in rows if not row.errors),
            {"04.252.011/0001-10": "ATIVA", "11.222.333/0001-81": "ATIVA"},
            date(2026, 10, 24),
        )
        sequential = list(iter_validated_chunks(rows, config, contexto, chunk_size=2, workers=1))
        parallel = list(iter_validated_chunks(rows, config, contexto, chunk_size=2, workers=2))

        self.assertEqual(parallel, sequential)
        self.assertEqual([chunk.total for chunk in parallel], [2, 2, 2, 1])
        results = json.loads("[" + ",".join(chunk.content for chunk in parallel) + "]")
        self.assertEqual([row["row_number"] for row in results], list(range(2, 9)))
        self.assertTrue(results[0]["validation"]["aprovado"])
        self.assertFalse(results[1]["validation"]["aprovado"])
        self.assertIsNone(results[2]["validation"])

    def test_small_files_do_not_start_a_process_pool(self):
        config = carregar_configuracao(CONFIG_PATH)
        with patch("backend.app.validation.ProcessPoolExecutor") as pool:
            self.assertEqual(list(iter_validated_chunks([], config, ContextoValidacao())), [])
            chunks = list(iter_validated_chunks(
                [parse_row((2, {}))], config, ContextoValidacao(), workers=2
            ))
        pool.assert_not_called()
        self.assertEqual((chunks[0].total, chunks[0].valid), (1, 0))

    def test_submission_is_bounded_and_pending_work_is_cancelled_when_closed(self):
        submitted = []
        cancelled = []
        consumed = []

        class Future:
            def __init__(self, chunk):
                self.chunk = chunk

            def result(self):
                return ValidatedChunk("", len(self.chunk), 0, 0)

            def cancel(self):
                cancelled.append(self)

        class Executor:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def submit(self, function, chunk):
                submitted.append(chunk)
                return Future(chunk)

        def rows():
            for index in range(100):
                consumed.append(index)
                yield index

        with patch("backend.app.validation.ProcessPoolExecutor", Executor):
            chunks = iter_validated_chunks(rows(), {}, ContextoValidacao(), chunk_size=2, workers=3)
            self.assertEqual(next(chunks).total, 2)
            self.assertEqual(len(submitted), 3)
            self.assertEqual(len(consumed), 6)
            chunks.close()
        self.assertEqual(len(cancelled), 2)
