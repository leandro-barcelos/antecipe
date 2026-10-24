import asyncio
import io
import json
import logging
import unittest
from unittest.mock import patch
from uuid import UUID

from backend.app.logging_config import RequestLoggingMiddleware, configure_logging, log_event
from backend.tests import test_validation_endpoint as endpoint_tests


SECRET = "CSV_PRIVATE_DOCUMENT_789654"


class LoggingTests(unittest.IsolatedAsyncioTestCase):
    csv_bytes = endpoint_tests.ValidationEndpointTests.csv_bytes
    request = endpoint_tests.ValidationEndpointTests.request

    def setUp(self):
        endpoint_tests.ValidationEndpointTests.setUp(self)
        self.output = io.StringIO()
        configure_logging(stream=self.output, level="DEBUG")

    def tearDown(self):
        configure_logging(level="CRITICAL")

    def events(self):
        self.assertNotIn(SECRET, self.output.getvalue())
        return [json.loads(line) for line in self.output.getvalue().splitlines()]

    async def test_counts_and_phases_without_csv_values_in_both_modes(self):
        for pricing in (False, True):
            status, result = await self.request(
                json.dumps(self.config), filename=SECRET + ".csv",
                content=self.csv_bytes(("100,00", "50,00", "bad"), ids=(SECRET, SECRET + "2", SECRET + "3"), maturity="31/01/2026"),
                precificar=pricing,
            )
            self.assertEqual(status, 200)
            events = self.events()
            summary = [e for e in events if e["event"] == "processing_summary"][-1]
            self.assertEqual([summary[k] for k in ("linhas", "aprovados", "barrados")], [3, 1, 2])
            self.assertEqual(events[-1]["event"], "request_completed")
            self.assertEqual(events[-2]["phase"], "limpeza")
        for value in ("valor_nominal", "valor_liquido", "ANTECIPE FIDC", "04.252.011/0001-10", "31/01/2026"):
            self.assertNotIn(value, self.output.getvalue())

    async def test_exceptions_library_messages_and_extra_fields_are_discarded(self):
        try:
            raise RuntimeError(SECRET)
        except RuntimeError:
            logging.getLogger("uvicorn.error").exception("%s", SECRET, stack_info=True)
        logging.getLogger("multipart").debug(SECRET)
        logging.getLogger("uvicorn.access").info(SECRET)
        log_event("processing_summary", linhas=1, config=SECRET, filename=SECRET, error=SECRET)
        self.assertEqual([e["event"] for e in self.events()], ["library_log", "library_log", "processing_summary"])
        with patch("backend.app.main.parse_csv", side_effect=RuntimeError(SECRET)):
            with self.assertRaises(RuntimeError):
                await self.request(json.dumps(self.config))
        self.assertEqual(self.events()[-1]["event"], "request_failed")

    async def test_invalid_config_file_and_unknown_route_are_safe(self):
        for kwargs in (
            {"config": SECRET},
            {"config": None},
            {"config": json.dumps(self.config), "filename": SECRET + ".zip", "content": SECRET.encode()},
            {"config": json.dumps(self.config), "path": "/" + SECRET},
        ):
            status, _ = await self.request(**kwargs)
            self.assertGreaterEqual(status, 400)
        self.assertEqual(self.events()[-1]["route"], "unmatched")

    async def test_concurrent_threadpool_contexts_are_isolated(self):
        strict = json.loads(json.dumps(self.config))
        for rule in strict["validadores"]:
            if rule["codigo"] == "VALOR_MINIMO":
                rule["parametros"]["valor_minimo"] = 1000
        content = self.csv_bytes(("100,00",))
        await asyncio.gather(self.request(json.dumps(self.config), content=content), self.request(json.dumps(strict), content=content))
        summaries = [e for e in self.events() if e["event"] == "processing_summary"]
        self.assertEqual(len({e["request_id"] for e in summaries}), 2)
        self.assertEqual({e["aprovados"] for e in summaries}, {0, 1})
        for summary in summaries:
            UUID(summary["request_id"])

    async def test_response_header_is_generated_and_send_failure_is_logged(self):
        async def application(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": SECRET.encode()})
        headers = []
        async def send(message):
            if message["type"] == "http.response.start":
                headers.extend(message["headers"])
            else:
                raise OSError(SECRET)
        scope = {"type": "http", "path": "/api/validate", "method": "POST", "headers": [(b"x-request-id", SECRET.encode())], "query_string": SECRET.encode()}
        with self.assertRaises(OSError):
            await RequestLoggingMiddleware(application)(scope, None, send)
        request_id = dict(headers)[b"x-request-id"].decode()
        UUID(request_id)
        self.assertEqual(self.events()[-1]["request_id"], request_id)
        self.assertEqual(self.events()[-1]["event"], "request_interrupted")

    async def test_health_is_quiet_at_info_and_output_failure_does_not_raise(self):
        configure_logging(stream=self.output, level="INFO")
        async def application(scope, receive, send):
            await send({"type": "http.response.start", "status": 200})
            await send({"type": "http.response.body", "body": b""})
        async def send(message):
            pass
        await RequestLoggingMiddleware(application)({"type": "http", "path": "/api/health", "method": "GET"}, None, send)
        self.assertEqual(self.events(), [])
        with patch.object(self.output, "write", side_effect=OSError(SECRET)):
            log_event("service_ready")
