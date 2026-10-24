
# app/pricing.py

from datetime import date
from decimal import Decimal, ROUND_HALF_UP


CENT = Decimal("0.01")


def calculate_pricing(
    receivable: dict,
    config: dict,
    reference_date: date,
) -> dict:
    """
    Calcula o desconto simples e o valor líquido.

    Deve ser chamado somente após a aprovação
    do recebível pelo motor de elegibilidade.
    """

    pricing = config["precificacao"]

    method = pricing["metodo"]

    if method != "DESCONTO_SIMPLES":
        raise ValueError(
            f"Método de precificação não suportado: {method}"
        )

    nominal = Decimal(
        str(receivable["VALOR_NOMINAL"])
    )

    rate = Decimal(
        str(pricing["taxa_mensal_percentual"])
    ) / Decimal("100")

    day_base = Decimal(
        str(pricing["base_dias"])
    )

    if day_base <= 0:
        raise ValueError("Base de dias deve ser positiva")

    if nominal < 0:
        raise ValueError("Valor nominal inválido")

    due_date = receivable["DATA_VENCIMENTO_ORIGINAL"]

    days = (due_date - reference_date).days

    if days < 0:
        raise ValueError(
            "Não é possível precificar um título vencido"
        )

    discount = (
        nominal * rate * Decimal(days) / day_base
    ).quantize(CENT, rounding=ROUND_HALF_UP)

    net_value = (
        nominal - discount
    ).quantize(CENT, rounding=ROUND_HALF_UP)

    return {
        "document": receivable["NU_DOCUMENTO"],
        "nominal_value": str(nominal.quantize(CENT)),
        "days_to_maturity": days,
        "monthly_rate_percent": str(
            pricing["taxa_mensal_percentual"]
        ),
        "discount": str(discount),
        "net_value": str(net_value),
        "currency": "BRL",
    }
