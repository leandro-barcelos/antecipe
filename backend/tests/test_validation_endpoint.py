import asyncio
import csv
import io
import json
import unittest
import weakref
import zipfile
from decimal import Decimal
from functools import partial
from pathlib import Path
from unittest.mock import patch

from backend.app.csv_parser import REQUIRED_COLUMNS, ParseResult
from backend.app.main import _write_validation_response, app


CONFIG_PATH = Path(__file__).resolve().parents[1] / "data/validadores_antecipe.json"


class ValidationEndpointTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        for rule in self.config["validadores"]:
            rule["ativo"] = rule["codigo"] == "VALOR_MINIMO"

    def csv_bytes(self, amounts=("100,00", "99,99", "inválido"), documents=None):
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=REQUIRED_COLUMNS, delimiter=";")
        writer.writeheader()
        for index, amount in enumerate(amounts):
            writer.writerow({
                "DOC_SACADO": documents[index] if documents else "04.252.011/0001-10",
                "DOC_CEDENTE": "11.222.333/0001-81",
                "VALOR_NOMINAL": amount,
                "DATA_AQUISICAO": "01/01/2026",
                "DATA_VENCIMENTO_ORIGINAL": "31/12/2026",
            })
        return stream.getvalue().encode("utf-8")

    async def request(self, config, filename="estoque.csv", content=None, path="/api/validate"):
        # Exercise the ASGI multipart request without an external HTTP client.
        boundary = "antecipe-test-boundary"
        parts = []
        if config is not None:
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="config"\r\n\r\n'
                f'{config}\r\n'.encode()
            )
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
            + (self.csv_bytes() if content is None else content)
            + f'\r\n--{boundary}--\r\n'.encode()
        )
        body = b"".join(parts)
        messages = []
        request_sent = False
        disconnected = asyncio.Event()

        async def receive():
            nonlocal request_sent
            if request_sent:
                await disconnected.wait()
                return {"type": "http.disconnect"}
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            messages.append(message)

        await app({
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "POST", "scheme": "http", "path": path,
            "raw_path": path.encode(), "query_string": b"", "root_path": "",
            "headers": [
                (b"content-type", f"multipart/form-data; boundary={boundary}".encode()),
                (b"content-length", str(len(body)).encode()),
            ],
            "client": ("127.0.0.1", 12345), "server": ("testserver", 80),
        }, receive, send)
        status = next(m["status"] for m in messages if m["type"] == "http.response.start")
        response = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
        return status, json.loads(response)

    async def test_validates_rows_using_request_config_and_preserves_parse_errors(self):
        status, result = await self.request(json.dumps(self.config))
        self.assertEqual(status, 200)
        self.assertEqual((result["total"], result["valid"], result["invalid"]), (3, 2, 1))
        self.assertEqual((result["approved"], result["rejected"]), (1, 1))
        first, second, invalid = result["results"]
        self.assertTrue(first["validation"]["aprovado"])
        self.assertFalse(second["validation"]["aprovado"])
        self.assertEqual(first["validation"]["resultados"][0]["codigo"], "VALOR_MINIMO")
        self.assertEqual(invalid["row_number"], 4)
        self.assertIsNone(invalid["validation"])
        self.assertTrue(invalid["errors"])

        for rule in self.config["validadores"]:
            if rule["codigo"] == "VALOR_MINIMO":
                rule["parametros"]["valor_minimo"] = 50
        status, result = await self.request(json.dumps(self.config))
        self.assertEqual(status, 200)
        self.assertEqual(result["approved"], 2)

    async def test_zip_uses_full_parseable_base_for_concentration(self):
        for rule in self.config["validadores"]:
            rule["ativo"] = rule["codigo"] == "CONCENTRACAO_MAXIMA_SACADO"
            if rule["ativo"]:
                rule["parametros"]["percentual_maximo"] = 10
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("estoque.csv", self.csv_bytes(
                ("100,00", "900,00", "inválido"),
                ("04.252.011/0001-10", "11.222.333/0001-81", "04.252.011/0001-10"),
            ))
        status, result = await self.request(json.dumps(self.config), "estoque.zip", archive.getvalue())
        self.assertEqual(status, 200)
        self.assertEqual((result["approved"], result["rejected"], result["invalid"]), (1, 1, 1))
        self.assertTrue(result["results"][0]["validation"]["aprovado"])
        self.assertFalse(result["results"][1]["validation"]["aprovado"])

    async def test_two_passes_do_not_retain_rows_and_clean_up_files_after_response(self):
        class RowData(dict):
            pass

        references = []
        paths = []

        def parse_incrementally(path):
            paths.append(path)
            for index in range(100):
                data = RowData({
                    "DOC_SACADO": "04.252.011/0001-10",
                    "DOC_CEDENTE": "11.222.333/0001-81",
                    "VALOR_NOMINAL": Decimal("100"),
                })
                references.append(weakref.ref(data))
                yield ParseResult(index + 2, data, [])
                self.assertLessEqual(sum(ref() is not None for ref in references), 4)

        with (
            patch("backend.app.main.parse_csv", side_effect=parse_incrementally),
            patch("backend.app.main._write_validation_response", side_effect=partial(
                _write_validation_response, chunk_size=2, workers=1
            )),
        ):
            status, result = await self.request(json.dumps(self.config))

        self.assertEqual(status, 200)
        self.assertEqual((result["total"], result["approved"]), (100, 100))
        self.assertEqual(len(paths), 2)
        self.assertEqual(paths[0], paths[1])
        self.assertFalse(paths[0].parent.exists())
        self.assertTrue(all(ref() is None for ref in references))

    async def test_parallel_blocks_preserve_response_order_and_counts(self):
        with patch("backend.app.main._write_validation_response", side_effect=partial(
            _write_validation_response, chunk_size=2, workers=2
        )):
            status, result = await self.request(json.dumps(self.config))

        self.assertEqual(status, 200)
        self.assertEqual((result["total"], result["valid"], result["invalid"]), (3, 2, 1))
        self.assertEqual((result["approved"], result["rejected"]), (1, 1))
        self.assertEqual([row["row_number"] for row in result["results"]], [2, 3, 4])
        self.assertTrue(result["results"][0]["validation"]["aprovado"])
        self.assertFalse(result["results"][1]["validation"]["aprovado"])
        self.assertIsNone(result["results"][2]["validation"])

    async def test_second_pass_errors_return_400_and_remove_temporary_files(self):
        paths = []

        def fail_on_second_pass(path):
            paths.append(path)
            if len(paths) == 2:
                raise csv.Error("Erro na segunda passagem")
            return iter(())

        with patch("backend.app.main.parse_csv", side_effect=fail_on_second_pass):
            status, result = await self.request(json.dumps(self.config))

        self.assertEqual(status, 400)
        self.assertEqual(result["detail"], "Erro na segunda passagem")
        self.assertFalse(paths[0].parent.exists())

    async def test_header_only_and_all_invalid_rows_produce_valid_json(self):
        for amounts in ((), ("inválido",)):
            with self.subTest(amounts=amounts):
                status, result = await self.request(
                    json.dumps(self.config), content=self.csv_bytes(amounts)
                )
                self.assertEqual(status, 200)
                self.assertEqual(result["total"], len(amounts))
                self.assertEqual(result["invalid"], len(amounts))
                self.assertEqual((result["valid"], result["approved"], result["rejected"]), (0, 0, 0))

    async def test_rejects_missing_malformed_or_non_object_json_config(self):
        for config in (None, "{", "[]", "null"):
            with self.subTest(config=config):
                status, _ = await self.request(config)
                self.assertEqual(status, 422 if config is None else 400)

    async def test_rejects_invalid_config_structure_and_rule_parameters(self):
        for config in (
            {}, {"validadores": None}, {"validadores": [None]},
            {"validadores": [{"codigo": "VALOR_MINIMO", "ativo": True, "parametros": {}}]},
            {"validadores": [{"codigo": "DESCONHECIDO", "ativo": True, "parametros": {}}]},
            {"validadores": [{"codigo": "TIPO_RECEBIVEL", "ativo": True, "parametros": {"tipos_aceitos": "Duplicata"}}]},
            {"validadores": [{"codigo": "PRAZO_MAXIMO", "ativo": True, "parametros": {"prazo_maximo_dias": "180"}}]},
            {"validadores": [{"codigo": "VALOR_MINIMO", "ativo": True, "parametros": {"valor_minimo": "NaN"}}]},
        ):
            with self.subTest(config=config):
                status, result = await self.request(json.dumps(config))
                self.assertEqual(status, 400)
                self.assertIn("detail", result)

    async def test_rejects_unsupported_and_malformed_files(self):
        for filename, content in (("file.txt", b"text"), ("empty.csv", b""), ("bad.zip", b"bad")):
            with self.subTest(filename=filename):
                status, _ = await self.request(json.dumps(self.config), filename, content)
                self.assertEqual(status, 400)

    async def test_old_upload_route_was_removed(self):
        status, _ = await self.request(json.dumps(self.config), path="/api/upload")
        self.assertEqual(status, 404)
