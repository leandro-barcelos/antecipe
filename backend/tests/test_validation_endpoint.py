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
import tempfile
from unittest.mock import patch

from backend.app.csv_parser import REQUIRED_COLUMNS, ParseResult
from backend.app.main import TemporaryFileResponse, _write_validation_response, app
from starlette.requests import ClientDisconnect
from backend.app.situacao_cadastral import carregar_situacoes_cadastrais


CONFIG_PATH = Path(__file__).resolve().parents[1] / "data/validadores_antecipe.json"


class ValidationEndpointTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        for rule in self.config["validadores"]:
            rule["ativo"] = rule["codigo"] == "VALOR_MINIMO"

    def csv_bytes(
        self, amounts=("100,00", "99,99", "inválido"), documents=None, ids=None, funds=None,
        cedentes=None, acquisition="01/01/2026", maturity="31/12/2026",
    ):
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=REQUIRED_COLUMNS, delimiter=";")
        writer.writeheader()
        for index, amount in enumerate(amounts):
            fund = funds[index] if funds else self.config["fundo"]
            writer.writerow({
                "NOME_FUNDO": fund.get("nome", ""),
                "DOC_FUNDO": fund.get("cnpj", ""),
                "DOC_SACADO": documents[index] if documents else "04.252.011/0001-10",
                "DOC_CEDENTE": cedentes[index] if cedentes else "11.222.333/0001-81",
                "NU_DOCUMENTO": ids[index] if ids else f"{index + 1:09d}",
                "VALOR_NOMINAL": amount,
                "DATA_AQUISICAO": acquisition,
                "DATA_VENCIMENTO_ORIGINAL": maturity,
            })
        return stream.getvalue().encode("utf-8")

    async def request(self, config, filename="estoque.csv", content=None, path="/api/validate", precificar=False):
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
            "raw_path": path.encode(),
            "query_string": b"" if precificar is None else f"precificar={str(precificar).lower()}".encode(),
            "root_path": "",
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
        content = self.csv_bytes(ids=("725714", "1-759172", "000351153"))
        status, result = await self.request(json.dumps(self.config), content=content)
        self.assertEqual(status, 200)
        self.assertEqual(result, [
            {"linha": 2, "id": "725714", "status": "APROVADO", "valor_nominal": '100.00'},
            {"linha": 3, "id": "1-759172", "status": "BARRADO", "valor_nominal": '99.99', "barrado_por": ["VALOR_MINIMO"]},
            {"linha": 4, "id": "000351153", "status": "BARRADO", "valor_nominal": None, "barrado_por": ["ERRO_CSV"]},
        ])

        for rule in self.config["validadores"]:
            if rule["codigo"] == "VALOR_MINIMO":
                rule["parametros"]["valor_minimo"] = 50
        status, result = await self.request(json.dumps(self.config), content=content)
        self.assertEqual(status, 200)
        self.assertEqual([row["status"] for row in result], ["APROVADO", "APROVADO", "BARRADO"])
        self.assertNotIn("barrado_por", result[1])

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
        self.assertEqual(result, [
            {"linha": 2, "id": "000000001", "status": "APROVADO", "valor_nominal": '100.00'},
            {"linha": 3, "id": "000000002", "status": "BARRADO", "valor_nominal": '900.00', "barrado_por": ["CONCENTRACAO_MAXIMA_SACADO"]},
            {"linha": 4, "id": "000000003", "status": "BARRADO", "valor_nominal": None, "barrado_por": ["ERRO_CSV"]},
        ])

    async def test_single_import_does_not_retain_rows_and_cleans_up_files_after_response(self):
        class RowData(dict):
            pass

        references = []
        paths = []

        def parse_incrementally(path):
            paths.append(path)
            for index in range(100):
                data = RowData({
                    "NOME_FUNDO": self.config["fundo"]["nome"],
                    "DOC_FUNDO": self.config["fundo"]["cnpj"],
                    "DOC_SACADO": "04.252.011/0001-10",
                    "DOC_CEDENTE": "11.222.333/0001-81",
                    "NU_DOCUMENTO": f"{index:09d}",
                    "VALOR_NOMINAL": Decimal("100"),
                })
                references.append(weakref.ref(data))
                yield ParseResult(index + 2, data, [])
                self.assertLessEqual(sum(ref() is not None for ref in references), 4)

        with (
            patch("backend.app.main.parse_csv", side_effect=parse_incrementally),
            patch("backend.app.main._write_validation_response", side_effect=partial(
                _write_validation_response, chunk_size=2
            )),
        ):
            status, result = await self.request(json.dumps(self.config))

        self.assertEqual(status, 200)
        self.assertEqual(len(result), 100)
        self.assertTrue(all(row["status"] == "APROVADO" for row in result))
        self.assertEqual(len(paths), 1)
        self.assertFalse(paths[0].parent.exists())
        self.assertTrue(all(ref() is None for ref in references))

    async def test_sql_batches_preserve_response_order_and_counts(self):
        with patch("backend.app.main._write_validation_response", side_effect=partial(
            _write_validation_response, chunk_size=2
        )):
            status, result = await self.request(json.dumps(self.config))

        self.assertEqual(status, 200)
        self.assertEqual(result, [
            {"linha": 2, "id": "000000001", "status": "APROVADO", "valor_nominal": '100.00'},
            {"linha": 3, "id": "000000002", "status": "BARRADO", "valor_nominal": '99.99', "barrado_por": ["VALOR_MINIMO"]},
            {"linha": 4, "id": "000000003", "status": "BARRADO", "valor_nominal": None, "barrado_por": ["ERRO_CSV"]},
        ])

    async def test_fund_is_mandatory_and_normalized_with_different_batches(self):
        for rule in self.config["validadores"]:
            rule["ativo"] = False
        fund = self.config["fundo"]
        funds = (
            {"nome": " antecipe   fidc ", "cnpj": "92234400000180"},
            {**fund, "cnpj": "11.222.333/0001-81"},
            {**fund, "nome": "OUTRO FIDC"},
            {"cnpj": fund["cnpj"]}, {"nome": fund["nome"]}, {}, fund,
            {**fund, "cnpj": "92.234.400/0001-81"},
        )
        content = self.csv_bytes(("100,00",) * len(funds), funds=funds)
        expected = [
            {"linha": index + 2, "id": f"{index + 1:09d}", "status": "BARRADO", "valor_nominal": '100.00', "barrado_por": ["FUNDO_VALIDO"]}
            for index in range(len(funds))
        ]
        for index in (0, 1, 2, 6):
            expected[index] = {"linha": index + 2, "id": f"{index + 1:09d}", "status": "APROVADO", "valor_nominal": '100.00'}
        for batch_size in (1, 2):
            with (
                self.subTest(batch_size=batch_size),
                patch("backend.app.main._write_validation_response", side_effect=partial(
                    _write_validation_response, chunk_size=batch_size
                )),
            ):
                status, result = await self.request(json.dumps(self.config), content=content)
                self.assertEqual(status, 200)
                self.assertEqual(result, expected)

    async def test_funds_have_separate_concentration_bases(self):
        for rule in self.config["validadores"]:
            rule["ativo"] = rule["codigo"] == "CONCENTRACAO_MAXIMA_SACADO"
        content = self.csv_bytes(
            ("100,00", "900,00"),
            documents=("04.252.011/0001-10", "11.222.333/0001-81"),
            funds=(self.config["fundo"], {"nome": "OUTRO FIDC", "cnpj": "11.222.333/0001-81"}),
        )
        status, result = await self.request(json.dumps(self.config), content=content)
        self.assertEqual(status, 200)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["barrado_por"], ["CONCENTRACAO_MAXIMA_SACADO"])
        self.assertEqual(result[1]["barrado_por"], ["CONCENTRACAO_MAXIMA_SACADO"])

    async def test_rejects_invalid_fund_configuration(self):
        for fund in (None, {}, {"nome": " ", "cnpj": "92234400000180"}, {"nome": "ANTECIPE FIDC", "cnpj": "92234400000181"}):
            with self.subTest(fund=fund):
                config = {**self.config, "fundo": fund}
                status, result = await self.request(json.dumps(config))
                self.assertEqual(status, 400)
                self.assertIn("detail", result)
        config = {key: value for key, value in self.config.items() if key != "fundo"}
        status, _ = await self.request(json.dumps(config))
        self.assertEqual(status, 400)

    async def test_import_errors_return_400_and_remove_temporary_files(self):
        paths = []

        def fail_import(path):
            paths.append(path)
            raise csv.Error("Erro na importação")

        with patch("backend.app.main.parse_csv", side_effect=fail_import):
            status, result = await self.request(json.dumps(self.config))

        self.assertEqual(status, 400)
        self.assertEqual(result["detail"], "Erro na importação")
        self.assertFalse(paths[0].parent.exists())

    async def test_header_only_and_all_invalid_rows_produce_valid_json(self):
        for amounts in ((), ("inválido",)):
            with self.subTest(amounts=amounts):
                status, result = await self.request(
                    json.dumps(self.config), content=self.csv_bytes(amounts)
                )
                self.assertEqual(status, 200)
                self.assertEqual(len(result), len(amounts))
                for row in result:
                    self.assertEqual(row["status"], "BARRADO")
                    self.assertEqual(row["barrado_por"], ["ERRO_CSV"])

    async def test_barred_rows_include_failed_and_pending_rules_in_config_order(self):
        for rule in self.config["validadores"]:
            rule["ativo"] = rule["codigo"] in {"SITUACAO_CADASTRAL_SACADO", "VALOR_MINIMO"}
        status, result = await self.request(
            json.dumps(self.config), content=self.csv_bytes(("50,00",), ids=("000351156",))
        )
        self.assertEqual(status, 200)
        self.assertEqual(result, [{
            "linha": 2, "id": "000351156", "status": "BARRADO", "valor_nominal": '50.00',
            "barrado_por": ["SITUACAO_CADASTRAL_SACADO", "VALOR_MINIMO"],
        }])

    async def test_cadastral_status_uses_mock_csv_with_different_batches(self):
        for rule in self.config["validadores"]:
            rule["ativo"] = rule["codigo"] == "SITUACAO_CADASTRAL_SACADO"
        content = self.csv_bytes(
            ("100,00", "100,00", "100,00"),
            documents=("01000171000183", "03.638.251/0001-94", "04.252.011/0001-10"),
        )
        for batch_size in (1, 2):
            with (
                self.subTest(batch_size=batch_size),
                patch("backend.app.main.carregar_situacoes_cadastrais", wraps=carregar_situacoes_cadastrais) as loader,
                patch("backend.app.main._write_validation_response", side_effect=partial(
                    _write_validation_response, chunk_size=batch_size
                )),
            ):
                status, result = await self.request(json.dumps(self.config), content=content)
                self.assertEqual(status, 200)
                self.assertEqual(result, [
                    {"linha": 2, "id": "000000001", "status": "APROVADO", "valor_nominal": '100.00'},
                    {"linha": 3, "id": "000000002", "status": "BARRADO", "valor_nominal": '100.00', "barrado_por": ["SITUACAO_CADASTRAL_SACADO"]},
                    {"linha": 4, "id": "000000003", "status": "BARRADO", "valor_nominal": '100.00', "barrado_por": ["SITUACAO_CADASTRAL_SACADO"]},
                ])
                loader.assert_called_once()

    async def test_disabled_cadastral_rule_does_not_load_mock_csv(self):
        with patch("backend.app.main.carregar_situacoes_cadastrais") as loader:
            status, _ = await self.request(json.dumps(self.config))
        self.assertEqual(status, 200)
        loader.assert_not_called()

    async def test_cadastral_decision_follows_mock_even_when_reference_disagrees(self):
        for rule in self.config['validadores']:
            rule['ativo'] = rule['codigo'] == 'SITUACAO_CADASTRAL_SACADO'
        status, result = await self.request(
            json.dumps(self.config),
            content=self.csv_bytes(('100,00',), documents=('28.297.129/0002-03',)),
        )
        self.assertEqual(status, 200)
        self.assertEqual(result[0]['status'], 'APROVADO')

    async def test_rejects_missing_malformed_or_non_object_json_config(self):
        for config in (None, "{", "[]", "null"):
            with self.subTest(config=config):
                status, _ = await self.request(config)
                self.assertEqual(status, 422 if config is None else 400)

    async def test_portfolio_excludes_duplicates_and_sums_only_approved_titles(self):
        content = self.csv_bytes(
            ("1000,00", "2000,00", "1000,00", "50,00", "inválido"),
            ids=("000351153", "1-759172", "000351153", "LOW", "BAD"),
            maturity="31/01/2026",
        )
        expected = {
            "resultados": [
                {"linha": 2, "id": "000351153", "status": "APROVADO", "valor_nominal": "1000.00", "valor_liquido": "980.00"},
                {"linha": 3, "id": "1-759172", "status": "APROVADO", "valor_nominal": "2000.00", "valor_liquido": "1960.00"},
                {"linha": 4, "id": "000351153", "status": "BARRADO", "valor_nominal": '1000.00', "barrado_por": ["DUPLICADO"]},
                {"linha": 5, "id": "LOW", "status": "BARRADO", "valor_nominal": '50.00', "barrado_por": ["VALOR_MINIMO"]},
                {"linha": 6, "id": "BAD", "status": "BARRADO", "valor_nominal": None, "barrado_por": ["ERRO_CSV"]},
            ],
            "totais": {"linhas": 5, "aprovados": 2, "barrados": 3, "duplicatas_excluidas": 1,
                       "valor_nominal": "3000.00", "valor_liquido": "2940.00"},
        }
        for batch_size in (1, 2):
            with (
                self.subTest(batch_size=batch_size),
                patch("backend.app.main._write_validation_response", side_effect=partial(
                    _write_validation_response, chunk_size=batch_size
                )),
            ):
                status, result = await self.request(json.dumps(self.config), content=content, precificar=True)
                self.assertEqual(status, 200)
                self.assertEqual(result, expected)

    async def test_duplicate_key_preserves_distinct_documents_and_normalizes_cnpjs(self):
        fund = self.config["fundo"]
        content = self.csv_bytes(
            ("100,00",) * 5, ids=("0001", "0001", "0001", "1", "0001"),
            documents=("04.252.011/0001-10", "11.222.333/0001-81", "04.252.011/0001-10", "04.252.011/0001-10", "04252011000110"),
            cedentes=("11.222.333/0001-81", "11.222.333/0001-81", "04.252.011/0001-10", "11.222.333/0001-81", "11222333000181"),
            funds=(fund, fund, fund, fund, {"nome": "antecipe fidc", "cnpj": "92234400000180"}),
            maturity="31/01/2026",
        )
        status, result = await self.request(json.dumps(self.config), content=content, precificar=True)
        self.assertEqual(status, 200)
        self.assertEqual([row["status"] for row in result["resultados"]], ["APROVADO"] * 4 + ["BARRADO"])
        self.assertEqual(result["resultados"][-1]["barrado_por"], ["DUPLICADO"])
        self.assertEqual(result["totais"]["valor_liquido"], "392.00")

    async def test_duplicates_do_not_increase_concentration(self):
        for rule in self.config["validadores"]:
            rule["ativo"] = rule["codigo"] == "CONCENTRACAO_MAXIMA_SACADO"
        content = self.csv_bytes(
            ("100,00", "100,00", "900,00"), ids=("A", "A", "B"),
            documents=("04.252.011/0001-10", "04.252.011/0001-10", "11.222.333/0001-81"),
        )
        status, result = await self.request(json.dumps(self.config), content=content)
        self.assertEqual(status, 200)
        self.assertEqual(result[0]["status"], "APROVADO")
        self.assertEqual(result[1]["barrado_por"], ["DUPLICADO"])
        self.assertEqual(result[2]["barrado_por"], ["CONCENTRACAO_MAXIMA_SACADO"])

    async def test_invalid_occurrence_does_not_exclude_a_valid_copy(self):
        content = self.csv_bytes(("inválido", "100,00"), ids=("001", "001"), maturity="31/01/2026")
        status, result = await self.request(json.dumps(self.config), content=content, precificar=True)
        self.assertEqual(status, 200)
        self.assertEqual(result["resultados"][0]["barrado_por"], ["ERRO_CSV"])
        self.assertEqual(result["resultados"][1]["status"], "APROVADO")
        self.assertEqual(result["totais"]["duplicatas_excluidas"], 0)
        self.assertEqual(result["totais"]["valor_liquido"], "98.00")

    async def test_portfolio_empty_and_invalid_prices_have_zero_totals(self):
        config = {**self.config, "precificacao": {**self.config["precificacao"], "taxa_mensal_percentual": 200}}
        for amounts in ((), ("100,00",)):
            with self.subTest(amounts=amounts):
                status, result = await self.request(
                    json.dumps(config), content=self.csv_bytes(amounts, maturity="31/01/2026"), precificar=True
                )
                self.assertEqual(status, 200)
                self.assertEqual(result["totais"]["aprovados"], 0)
                self.assertEqual(result["totais"]["valor_nominal"], "0.00")
                self.assertNotIn("desconto", result["totais"])
                self.assertEqual(result["totais"]["valor_liquido"], "0.00")
                if amounts:
                    self.assertEqual(result["resultados"][0]["barrado_por"], ["PRECIFICACAO_INVALIDA"])

    async def test_pricing_is_required_when_enabled_and_optional_for_diagnostics(self):
        config = {key: value for key, value in self.config.items() if key != "precificacao"}
        for precificar in (None, True):
            with self.subTest(precificar=precificar):
                status, _ = await self.request(json.dumps(config), precificar=precificar)
                self.assertEqual(status, 400)
        status, result = await self.request(json.dumps(config))
        self.assertEqual(status, 200)
        self.assertIsInstance(result, list)

    async def test_validate_prices_by_default_and_returns_totals(self):
        status, result = await self.request(
            json.dumps(self.config),
            content=self.csv_bytes(("1000,00",), maturity="31/01/2026"),
            precificar=None,
        )
        self.assertEqual(status, 200)
        self.assertEqual(result, {
            "resultados": [{
                "linha": 2, "id": "000000001", "status": "APROVADO",
                "valor_nominal": "1000.00",
                "valor_liquido": "980.00",
            }],
            "totais": {
                "linhas": 1, "aprovados": 1, "barrados": 0, "duplicatas_excluidas": 0,
                "valor_nominal": "1000.00", "valor_liquido": "980.00",
            },
        })

    async def test_nominal_value_is_returned_for_barred_and_invalid_date_rows(self):
        for precificar in (False, True):
            with self.subTest(precificar=precificar):
                status, result = await self.request(
                    json.dumps(self.config),
                    content=self.csv_bytes(('50,00', '0,00', 'inválido'), maturity='data inválida'),
                    precificar=precificar,
                )
                self.assertEqual(status, 200)
                rows = result['resultados'] if precificar else result
                self.assertEqual([row['valor_nominal'] for row in rows], ['50.00', '0.00', None])
                self.assertTrue(all(row['status'] == 'BARRADO' for row in rows))
                self.assertTrue(all('desconto' not in row and 'prazo_dias' not in row and 'valor_liquido' not in row for row in rows))
                if precificar:
                    self.assertEqual(result['totais']['valor_nominal'], '0.00')

    async def test_only_validate_route_is_available_for_processing(self):
        status, _ = await self.request(json.dumps(self.config), path="/api/portfolio", precificar=None)
        self.assertEqual(status, 404)
        paths = app.openapi()["paths"]
        self.assertNotIn("/api/portfolio", paths)
        parameter = next(
            parameter for parameter in paths["/api/validate"]["post"]["parameters"]
            if parameter["name"] == "precificar"
        )
        self.assertEqual(parameter["in"], "query")
        self.assertIs(parameter["schema"]["default"], True)

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
                status, result = await self.request(json.dumps({"fundo": self.config["fundo"], **config}))
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

    async def test_fractional_cents_and_individual_overflow_are_csv_errors(self):
        content = self.csv_bytes(
            ("100,005", "100,0000", "92233720368547758,08"), ids=("001", "002", "003")
        )
        status, result = await self.request(json.dumps(self.config), content=content)
        self.assertEqual(status, 200)
        self.assertEqual(result, [
            {"linha": 2, "id": "001", "status": "BARRADO", "valor_nominal": None, "barrado_por": ["ERRO_CSV"]},
            {"linha": 3, "id": "002", "status": "APROVADO", "valor_nominal": '100.00'},
            {"linha": 4, "id": "003", "status": "BARRADO", "valor_nominal": None, "barrado_por": ["ERRO_CSV"]},
        ])

    async def test_aggregate_overflow_returns_400_for_concentration_and_portfolio(self):
        content = self.csv_bytes(("92233720368547758,07",) * 2)
        for precificar in (False, True):
            with self.subTest(precificar=precificar):
                config = json.loads(json.dumps(self.config))
                config['precificacao']['taxa_mensal_percentual'] = 0
                if not precificar:
                    for rule in config['validadores']:
                        rule['ativo'] = rule['codigo'] == 'CONCENTRACAO_MAXIMA_SACADO'
                status, result = await self.request(json.dumps(config), content=content, precificar=precificar)
                self.assertEqual(status, 400)
                self.assertIn('64 bits', result['detail'])

    async def test_operation_date_is_captured_once_before_import(self):
        from datetime import date
        for rule in self.config['validadores']:
            rule['ativo'] = rule['codigo'] == 'NAO_VENCIDA'
        with patch('backend.app.main.data_operacao', return_value=date(2026, 12, 31)) as operation_date:
            status, result = await self.request(json.dumps(self.config), content=self.csv_bytes(('100,00',)))
        self.assertEqual(status, 200)
        self.assertEqual(result[0]['status'], 'APROVADO')
        operation_date.assert_called_once()

    async def test_concurrent_requests_use_isolated_databases(self):
        strict = json.loads(json.dumps(self.config))
        for rule in strict['validadores']:
            if rule['codigo'] == 'VALOR_MINIMO':
                rule['parametros']['valor_minimo'] = 1000
        content = self.csv_bytes(('100,00',))
        loose_result, strict_result = await asyncio.gather(
            self.request(json.dumps(self.config), content=content),
            self.request(json.dumps(strict), content=content),
        )
        self.assertEqual(loose_result[0], 200)
        self.assertEqual(strict_result[0], 200)
        self.assertEqual(loose_result[1][0]['status'], 'APROVADO')
        self.assertEqual(strict_result[1][0]['barrado_por'], ['VALOR_MINIMO'])

    async def test_temporary_response_cleans_up_on_send_failure_and_disconnect(self):
        for interrupt in ('failure', 'disconnect'):
            with self.subTest(interrupt=interrupt):
                temporary = tempfile.TemporaryDirectory(prefix='antecipe-response-test-')
                directory = Path(temporary.name)
                path = directory / 'response.json'
                path.write_bytes(b' ' * (256 * 1024))
                response = TemporaryFileResponse(path, temporary)
                disconnected = asyncio.Event()

                async def receive():
                    await disconnected.wait()
                    return {'type': 'http.disconnect'}

                async def send(message):
                    if message['type'] == 'http.response.body':
                        if interrupt == 'failure':
                            raise OSError('connection closed')
                        disconnected.set()
                        await asyncio.sleep(0)

                scope = {'type': 'http', 'method': 'POST', 'headers': [], 'asgi': {'version': '3.0', 'spec_version': '2.0'}}
                try:
                    if interrupt == 'failure':
                        with self.assertRaises((OSError, ClientDisconnect)):
                            await response(scope, receive, send)
                    else:
                        await response(scope, receive, send)
                    self.assertFalse(directory.exists())
                finally:
                    temporary.cleanup()
