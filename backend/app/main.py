
from contextlib import asynccontextmanager
from pathlib import Path
import json
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

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
        raise RuntimeError(
            f"Arquivo de configuração não encontrado: {CONFIG_PATH}"
        )

    with open(CONFIG_PATH, "r", encoding="utf-8") as file:
        app.state.config = json.load(file)

    logger.info("Configuração carregada com sucesso.")

    yield

    logger.info("Encerrando Antecipe API...")


# --------------------------------------------------
# FastAPI application
# --------------------------------------------------

app = FastAPI(
    title="Antecipe API",
    description=(
        "API para validação de elegibilidade e "
        "precificação de recebíveis."
    ),
    version="1.0.0",
    lifespan=lifespan
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
        "http://127.0.0.1:3000",
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
    return {
        "status": "ok",
        "service": "Antecipe API",
        "version": app.version
    }


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
        validators = [
            validator
            for validator in validators
            if validator["ativo"]
        ]

    return {
        "total": len(validators),
        "validators": validators
    }


# --------------------------------------------------
# Pricing configuration
# --------------------------------------------------

@app.get("/api/pricing/config", tags=["Pricing"])
async def get_pricing_config():
    return app.state.config["precificacao"]
