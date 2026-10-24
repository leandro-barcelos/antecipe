"""JSON logs on stdout, containing only allowlisted operational metadata."""
import json
import logging
import os
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4


_request = ContextVar("log_request", default=None)
_token = object()
EVENTS = frozenset({
    "service_starting", "service_ready", "service_stopped", "service_failed",
    "request_completed", "request_rejected", "request_failed", "request_interrupted",
    "phase_completed", "phase_failed", "processing_summary",
})
PHASES = frozenset({"importacao", "cadastro", "validacao", "precificacao", "exportacao", "limpeza"})
ROUTES = frozenset({"/api/validate", "/api/health", "/api/fund", "/api/validators", "/api/pricing/config", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})
METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
COUNTERS = frozenset({"linhas", "aprovados", "barrados", "duplicatas_excluidas"})


class JSONFormatter(logging.Formatter):
    def format(self, record):
        trusted = getattr(record, "safe_token", None) is _token
        fields = getattr(record, "safe_fields", {}) if trusted else {}
        event = record.msg if trusted and record.msg in EVENTS else "library_log"
        result = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": {10: "DEBUG", 20: "INFO", 30: "WARNING", 40: "ERROR", 50: "CRITICAL"}.get(record.levelno, "INFO"),
            "service": "backend", "event": event,
        }
        context = _request.get()
        if context:
            result.update(context)
        for key in COUNTERS | {"status"}:
            value = fields.get(key)
            if type(value) is int and 0 <= value <= 2**63 - 1:
                result[key] = value
        if fields.get("phase") in PHASES:
            result["phase"] = fields["phase"]
        duration = fields.get("duration_ms")
        if type(duration) is float and 0 <= duration < float("inf"):
            result["duration_ms"] = round(duration, 3)
        # Never format record messages, args, exception text, stack_info or other extras.
        return json.dumps(result, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


class SafeStreamHandler(logging.StreamHandler):
    def handleError(self, record):
        # Default logging diagnostics print raw arguments and exception messages.
        pass


def configure_logging(*, stream=None, level=None):
    selected = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    if selected not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        selected = "INFO"
    logging.raiseExceptions = False
    handler = SafeStreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(JSONFormatter())
    logging.basicConfig(handlers=[handler], level=selected, force=True)
    for logger in list(logging.root.manager.loggerDict.values()):
        if isinstance(logger, logging.Logger):
            for existing in logger.handlers[:]:
                logger.removeHandler(existing)
                existing.close()
            logger.propagate = True
            logger.setLevel(logging.NOTSET)
    logging.getLogger("uvicorn.access").disabled = True
    logging.captureWarnings(True)


def log_event(event, *, level=logging.INFO, **fields):
    logging.getLogger("antecipe").log(level, event, extra={"safe_token": _token, "safe_fields": fields})


@contextmanager
def phase(name):
    started = perf_counter()
    try:
        yield
    except BaseException:
        log_event("phase_failed", level=logging.ERROR, phase=name, duration_ms=(perf_counter() - started) * 1000)
        raise
    else:
        log_event("phase_completed", phase=name, duration_ms=(perf_counter() - started) * 1000)


class RequestLoggingMiddleware:
    """Log after response transmission and temporary file cleanup have finished."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = str(uuid4())
        route = scope.get("path")
        method = scope.get("method")
        token = _request.set({"request_id": request_id, "route": route if route in ROUTES else "unmatched",
                              "method": method if method in METHODS else "OTHER"})
        started = perf_counter()
        status, complete, interrupted, failed = None, False, False, False

        async def tracked_receive():
            nonlocal interrupted
            message = await receive()
            if message["type"] == "http.disconnect" and not complete:
                interrupted = True
            return message

        async def tracked_send(message):
            nonlocal status, complete, interrupted
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                message = {**message, "headers": [*headers, (b"x-request-id", request_id.encode())]}
            try:
                await send(message)
            except BaseException:
                interrupted = True
                raise
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                complete = True

        try:
            await self.app(scope, tracked_receive, tracked_send)
        except BaseException as exc:
            failed = True
            interrupted = interrupted or not isinstance(exc, Exception)
            raise
        finally:
            try:
                if interrupted:
                    event, severity = "request_interrupted", logging.WARNING
                elif failed or status is None or status >= 500:
                    event, severity = "request_failed", logging.ERROR
                elif status >= 400:
                    event, severity = "request_rejected", logging.WARNING
                elif not complete:
                    event, severity = "request_interrupted", logging.WARNING
                else:
                    event, severity = "request_completed", logging.DEBUG if route == "/api/health" else logging.INFO
                log_event(event, level=severity, status=status, duration_ms=(perf_counter() - started) * 1000)
            finally:
                _request.reset(token)
