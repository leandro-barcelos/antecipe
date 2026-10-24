from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .validator import normalizar_data


CENTAVO = Decimal("0.01")


def validar_precificacao(config):
    if not isinstance(config, dict) or config.get("metodo") != "DESCONTO_SIMPLES":
        raise ValueError("O método de precificação deve ser DESCONTO_SIMPLES")
    taxa = config.get("taxa_mensal_percentual")
    try:
        if isinstance(taxa, bool):
            raise ValueError
        taxa = Decimal(str(taxa))
        if not taxa.is_finite() or taxa < 0:
            raise ValueError
    except (InvalidOperation, ValueError):
        raise ValueError("taxa_mensal_percentual deve ser finita e não negativa") from None
    base = config.get("base_dias")
    if type(base) is not int or base <= 0:
        raise ValueError("base_dias deve ser um inteiro maior que zero")


@dataclass(frozen=True)
class PrecoTitulo:
    valor_nominal: Decimal
    desconto: Decimal
    valor_liquido: Decimal
    prazo_dias: int

    def como_dict(self):
        return {
            "valor_nominal": format(self.valor_nominal, ".2f"),
            "desconto": format(self.desconto, ".2f"),
            "valor_liquido": format(self.valor_liquido, ".2f"),
            "prazo_dias": self.prazo_dias,
        }


class Precificador:
    def __init__(self, config):
        self.taxa = Decimal(str(config["taxa_mensal_percentual"])) / 100
        self.base_dias = config["base_dias"]

    def calcular(self, recebivel):
        prazo = (
            normalizar_data(recebivel["DATA_VENCIMENTO_ORIGINAL"])
            - normalizar_data(recebivel["DATA_AQUISICAO"])
        ).days
        if prazo < 0:
            raise ValueError("O vencimento não pode ser anterior à aquisição")
        nominal = Decimal(str(recebivel["VALOR_NOMINAL"])).quantize(
            CENTAVO, rounding=ROUND_HALF_UP
        )
        desconto = (nominal * self.taxa * prazo / self.base_dias).quantize(
            CENTAVO, rounding=ROUND_HALF_UP
        )
        if desconto > nominal:
            raise ValueError("O desconto não pode exceder o valor nominal")
        return PrecoTitulo(nominal, desconto, nominal - desconto, prazo)
