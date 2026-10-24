import csv
import json
import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from shutil import copyfileobj
from tempfile import TemporaryDirectory
from zipfile import BadZipFile

from anyio import CancelScope
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from .config import carregar_configuracao, validar_configuracao
from .csv_parser import parse_csv
from .database import DEFAULT_CHUNK_SIZE, ReceivablesDatabase
from .portfolio import precificar_aprovados, resumo
from .situacao_cadastral import carregar_situacoes_cadastrais
from .validation import data_operacao, validar_base
from .logging_config import RequestLoggingMiddleware, configure_logging, log_event, phase

# --------------------------------------------------
# Configuration
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "data" / "validadores_antecipe.json"
SITUACOES_CADASTRAIS_PATH = BASE_DIR / "data" / "cnpj_situacao_mock.csv"

configure_logging()


# --------------------------------------------------
# Application lifecycle
# --------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):

    log_event("service_starting")

    if not CONFIG_PATH.exists():
        raise RuntimeError(f"Arquivo de configuração não encontrado: {CONFIG_PATH}")

    try:
        app.state.config = carregar_configuracao(CONFIG_PATH)
    except Exception:
        log_event("service_failed", level=logging.ERROR)
        raise

    log_event("service_ready")

    try:
        yield
    finally:
        log_event("service_stopped")


# --------------------------------------------------
# FastAPI application
# --------------------------------------------------

class LoggedFastAPI(FastAPI):
    async def __call__(self, scope, receive, send):
        await RequestLoggingMiddleware(super().__call__)(scope, receive, send)


app = LoggedFastAPI(
    title="Antecipe API",
    description=("API para validação de elegibilidade e precificação de recebíveis."),
    version="1.0.0",
    lifespan=lifespan,
)


# --------------------------------------------------
# CORS
# --------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000http://192.168.189.83:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


# --------------------------------------------------
# Health check
# --------------------------------------------------


@app.get("/api/health", tags=["System"])
async def health_check():
    return {"status": "ok", "service": "Antecipe API", "version": app.version}


# --------------------------------------------------
# Fund information
# --------------------------------------------------


@app.get("/api/fund", tags=["Fund"])
async def get_fund():
    return app.state.config["fundo"]


# --------------------------------------------------
# Validators configuration
# --------------------------------------------------


@app.get("/api/validators", tags=["Validators"])
async def get_validators(active_only: bool = False):

    validators = app.state.config["validadores"]

    if active_only:
        validators = [validator for validator in validators if validator["ativo"]]

    return {"total": len(validators), "validators": validators}

    return app.state.config["fundo"]


# --------------------------------------------------
# Receivables validation
# --------------------------------------------------
def _write_validation_response(
    file_path,
    response_path,
    config,
    *,
    chunk_size=DEFAULT_CHUNK_SIZE,
    precificar=True,
    data_referencia=None,
):
    reference = data_referencia if data_referencia is not None else data_operacao()
    try:
        with ReceivablesDatabase(response_path.with_suffix(".sqlite")) as database:
            with phase("importacao"):
                database.import_rows(parse_csv(file_path), chunk_size=chunk_size)
            if any(
                regra["ativo"] and regra["codigo"] == "SITUACAO_CADASTRAL_SACADO"
                for regra in config["validadores"]
            ):
                with phase("cadastro"):
                    database.import_statuses(
                        carregar_situacoes_cadastrais(SITUACOES_CADASTRAIS_PATH)
                    )
            with phase("validacao"):
                validar_base(database, config, data_referencia=reference)
            if precificar:
                with phase("precificacao"):
                    precificar_aprovados(database, config, chunk_size=chunk_size)
            totals = resumo(database) if precificar else None
            counts = database.connection.execute('''SELECT COUNT(*) AS linhas,
                COALESCE(SUM(aprovado),0) AS aprovados,
                COUNT(*)-COALESCE(SUM(aprovado),0) AS barrados,
                COALESCE(SUM(duplicado_de IS NOT NULL),0) AS duplicatas_excluidas
                FROM recebiveis''').fetchone()
            log_event("processing_summary", **dict(counts))
            with phase("exportacao"), response_path.open("w", encoding="utf-8") as output:
                output.write('{"resultados":[' if precificar else "[")
                first = True
                for record in database.iter_records(
                    precificar=precificar, chunk_size=chunk_size
                ):
                    if not first:
                        output.write(",")
                    output.write(
                        json.dumps(
                            record,
                            ensure_ascii=False,
                            allow_nan=False,
                            separators=(",", ":"),
                        )
                    )
                    first = False
                output.write("]")
                if precificar:
                    output.write(',"totais":')
                    json.dump(totals, output, ensure_ascii=False)
                    output.write("}")
    except sqlite3.OperationalError as exc:
        if "integer overflow" in str(exc).lower():
            raise ValueError(
                "Soma financeira excede o limite de centavos de 64 bits"
            ) from exc
        raise


class TemporaryFileResponse(FileResponse):
    """Clean up also when transmission is interrupted or send() raises."""

    def __init__(self, path, temporary):
        super().__init__(path, media_type="application/json")
        self.temporary = temporary

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            with CancelScope(shield=True):
                await run_in_threadpool(_cleanup_temporary, self.temporary)


def _cleanup_temporary(temporary):
    with phase("limpeza"):
        temporary.cleanup()


def _process_receivables(file, config, *, precificar=True):
    try:
        try:
            config = json.loads(config)
            validar_configuracao(config, exigir_precificacao=precificar)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".csv", ".zip"}:
            raise HTTPException(
                status_code=400,
                detail="Envie um arquivo CSV ou ZIP contendo um CSV.",
            )

        temporary = TemporaryDirectory(prefix="antecipe-")
        try:
            directory = Path(temporary.name)
            file_path = directory / f"input{suffix}"
            response_path = directory / "response.json"
            with file_path.open("wb") as destination:
                copyfileobj(file.file, destination, length=1024 * 1024)

            try:
                _write_validation_response(
                    file_path, response_path, config, precificar=precificar
                )
            except (ValueError, UnicodeError, csv.Error, BadZipFile) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            file_path.unlink()
            return TemporaryFileResponse(response_path, temporary)
        except BaseException:
            _cleanup_temporary(temporary)
            raise
    finally:
        file.file.close()


@app.post("/api/validate", tags=["Validation"])
def validate_receivables(
    file: UploadFile = File(...),
    config: str = Form(..., description="Configuração dos validadores e precificação em JSON"),
    precificar: bool = True,
):
    return _process_receivables(file, config, precificar=precificar)


# --------------------------------------------------
# Pricing configuration
# --------------------------------------------------


@app.get("/api/pricing/config", tags=["Pricing"])
async def get_pricing_config():
    return app.state.config["precificacao"]
