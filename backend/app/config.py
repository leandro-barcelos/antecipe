import json
from decimal import Decimal, InvalidOperation

from validate_docbr import CNPJ

from .pricing import validar_precificacao
from .validator import RULES


def validar_configuracao(config, *, exigir_precificacao=False):
    if not isinstance(config, dict) or not isinstance(config.get("validadores"), list):
        raise ValueError("A configuração deve conter uma lista de validadores")

    fundo = config.get("fundo")
    if (
        not isinstance(fundo, dict)
        or not isinstance(fundo.get("nome"), str)
        or not fundo["nome"].strip()
    ):
        raise ValueError("A configuração deve conter um fundo com nome válido")
    cnpj = fundo.get("cnpj")
    if not isinstance(cnpj, str) or not CNPJ().validate(cnpj.strip()):
        raise ValueError("O CNPJ do fundo deve ser válido")

    if exigir_precificacao or "precificacao" in config:
        validar_precificacao(config.get("precificacao"))

    for regra in config["validadores"]:
        if (
            not isinstance(regra, dict)
            or not isinstance(regra.get("codigo"), str)
            or not isinstance(regra.get("ativo"), bool)
            or not isinstance(regra.get("parametros"), dict)
        ):
            raise ValueError("Cada validador deve conter codigo, ativo e parametros válidos")

        if not regra["ativo"]:
            continue

        codigo = regra["codigo"]
        if codigo not in RULES:
            raise ValueError(f"Validador não suportado: {codigo}")

        parametros = regra["parametros"]
        campo_lista = {
            "SITUACAO_CADASTRAL_SACADO": "situacoes_aceitas",
            "TIPO_RECEBIVEL": "tipos_aceitos",
        }.get(codigo)
        if campo_lista:
            valores = parametros.get(campo_lista)
            if not isinstance(valores, list) or any(
                not isinstance(valor, str) or not valor.strip() for valor in valores
            ):
                raise ValueError(f"{campo_lista} deve ser uma lista de textos válidos")

        campo_prazo = {
            "PRAZO_MAXIMO": "prazo_maximo_dias",
            "PRAZO_MINIMO": "prazo_minimo_dias",
        }.get(codigo)
        if campo_prazo:
            prazo = parametros.get(campo_prazo)
            if type(prazo) is not int or prazo < 0:
                raise ValueError(f"{campo_prazo} deve ser um inteiro não negativo")

        if codigo == "VALOR_MINIMO":
            _validar_numero(parametros.get("valor_minimo"), "valor_minimo")

        if codigo in {"CONCENTRACAO_MAXIMA_SACADO", "CONCENTRACAO_MAXIMA_CEDENTE"}:
            agrupamento = parametros.get("agrupamento", "CNPJ")
            if agrupamento not in ("CNPJ", "RAIZ_CNPJ"):
                raise ValueError(f"Agrupamento não suportado: {agrupamento}")

            percentual = _validar_numero(
                parametros.get("percentual_maximo"), "percentual_maximo"
            )
            if percentual > 100:
                raise ValueError("Percentual máximo deve estar entre 0 e 100")


def _validar_numero(valor, campo):
    try:
        if isinstance(valor, bool):
            raise ValueError
        numero = Decimal(str(valor))
        if not numero.is_finite() or numero < 0:
            raise ValueError
    except (InvalidOperation, ValueError):
        raise ValueError(f"{campo} deve ser um número finito e não negativo") from None
    return numero


def carregar_configuracao(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        config = json.load(file)

    validar_configuracao(config)
    return config
