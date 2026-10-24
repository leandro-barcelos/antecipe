import csv
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from shutil import copyfileobj
from tempfile import TemporaryDirectory
from zipfile import BadZipFile

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from .config import carregar_configuracao, validar_configuracao
from .csv_parser import parse_csv
from .validation import DEFAULT_CHUNK_SIZE, iter_validated_chunks
from .validator import ContextoValidacao

# --------------------------------------------------
# Configuration
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "data" / "validadores_antecipe.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("antecipe")


# --------------------------------------------------
# Application lifecycle
# --------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):

    logger.info("Iniciando Antecipe API...")

    if not CONFIG_PATH.exists():
        raise RuntimeError(f"Arquivo de configuração não encontrado: {CONFIG_PATH}")

    app.state.config = carregar_configuracao(CONFIG_PATH)

    logger.info("Configuração carregada com sucesso.")

    yield

    logger.info("Encerrando Antecipe API...")


# --------------------------------------------------
# FastAPI application
# --------------------------------------------------

app = FastAPI(
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
    file_path, response_path, filename, config, *, chunk_size=DEFAULT_CHUNK_SIZE, workers=None
):
    contexto = ContextoValidacao(
        result.data for result in parse_csv(file_path) if not result.errors
    )
    total = valid = approved = 0

    with response_path.open("w", encoding="utf-8") as output:
        output.write('{"filename":')
        json.dump(filename, output, ensure_ascii=False)
        output.write(',"results":[')

        for chunk in iter_validated_chunks(
            parse_csv(file_path), config, contexto, chunk_size=chunk_size, workers=workers
        ):
            if total:
                output.write(",")
            output.write(chunk.content)
            total += chunk.total
            valid += chunk.valid
            approved += chunk.approved

        output.write("],")
        summary = {
            "total": total,
            "valid": valid,
            "invalid": total - valid,
            "approved": approved,
            "rejected": valid - approved,
        }
        output.write(json.dumps(summary)[1:])


@app.post("/api/validate", tags=["Validation"])
def validate_receivables(
    file: UploadFile = File(...),
    config: str = Form(..., description="Configuração dos validadores em JSON"),
):
    try:
        try:
            config = json.loads(config)
            validar_configuracao(config)
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
                _write_validation_response(file_path, response_path, file.filename, config)
            except (ValueError, UnicodeError, csv.Error, BadZipFile) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            file_path.unlink()
            return FileResponse(
                response_path,
                media_type="application/json",
                background=BackgroundTask(temporary.cleanup),
            )
        except BaseException:
            temporary.cleanup()
            raise
    finally:
        file.file.close()


# --------------------------------------------------
# Pricing configuration
# --------------------------------------------------


@app.get("/api/pricing/config", tags=["Pricing"])
async def get_pricing_config():
    return app.state.config["precificacao"]
