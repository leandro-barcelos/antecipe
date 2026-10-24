
# app/portfolio.py

from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
import re

from app.csv_parser import parse_csv


def normalize_cnpj(value):
    return re.sub(r"\D", "", str(value or ""))


def cnpj_root(value):
    cnpj = normalize_cnpj(value)
    return cnpj[:8] if len(cnpj) == 14 else None


class Portfolio:
    def __init__(
        self,
        file_path: str | Path,
        fund_cnpj: str,
        reference_date: date = date(2026, 10, 22),
    ):
        self.fund_cnpj = normalize_cnpj(fund_cnpj)
        self.reference_date = reference_date

        self.total_exposure = Decimal("0")
        self.sacado_exposure = defaultdict(
            lambda: Decimal("0")
        )
        self.cedente_exposure = defaultdict(
            lambda: Decimal("0")
        )

        self.document_keys = set()
        self.total_rows = 0
        self.fund_rows = 0

        self.load(file_path)

    @staticmethod
    def document_key(receivable):
        return (
            normalize_cnpj(receivable["DOC_CEDENTE"]),
            str(receivable["NU_DOCUMENTO"]).strip(),
            str(receivable["TIPO_RECEBIVEL"]).strip(),
        )

    def load(self, file_path):
        for result in parse_csv(
            file_path,
            parallel=False,
            chunk_size=5000,
        ):
            self.total_rows += 1

            if result.errors:
                raise ValueError(
                    f"Linha {result.row_number}: "
                    f"{'; '.join(result.errors)}"
                )

            row = result.data

            # Índice global de possíveis duplicidades
            self.document_keys.add(
                self.document_key(row)
            )

            if normalize_cnpj(row["DOC_FUNDO"]) != self.fund_cnpj:
                continue

            self.fund_rows += 1

            # Exposição ativa na data-base.
            # Hipótese: vencimento >= data-base.
            if (
                row["DATA_VENCIMENTO_ORIGINAL"]
                < self.reference_date
            ):
                continue

            amount = row["VALOR_NOMINAL"]

            self.total_exposure += amount

            sacado = cnpj_root(row["DOC_SACADO"])
            cedente = normalize_cnpj(row["DOC_CEDENTE"])

            if sacado:
                self.sacado_exposure[sacado] += amount

            if cedente:
                self.cedente_exposure[cedente] += amount

    def is_duplicate(self, receivable):
        return (
            self.document_key(receivable)
            in self.document_keys
        )

    def check_concentration(
        self,
        receivable,
        max_percent,
        group_by="RAIZ_CNPJ",
        entity="sacado",
        additional_total=Decimal("0"),
        additional_exposure=Decimal("0"),
    ):
        """
        Simula concentração após inclusão do título.

        additional_total:
            Valor total de títulos já aprovados no lote.

        additional_exposure:
            Valor aprovado no lote para o mesmo grupo.
        """

        amount = Decimal(
            str(receivable["VALOR_NOMINAL"])
        )

        if entity == "sacado":
            document = receivable["DOC_SACADO"]
            exposures = self.sacado_exposure

        elif entity == "cedente":
            document = receivable["DOC_CEDENTE"]
            exposures = self.cedente_exposure

        else:
            raise ValueError("Entidade inválida")

        if group_by == "RAIZ_CNPJ":
            key = cnpj_root(document)
        elif group_by == "CNPJ":
            key = normalize_cnpj(document)
        else:
            raise ValueError(
                f"Agrupamento não suportado: {group_by}"
            )

        if not key:
            raise ValueError("CNPJ inválido para concentração")

        if entity == "cedente" and group_by == "RAIZ_CNPJ":
            raise ValueError(
                "Índice de cedente por raiz não configurado"
            )

        if entity == "sacado" and group_by == "CNPJ":
            raise ValueError(
                "Índice de sacado por CNPJ não configurado"
            )

        current = exposures.get(key, Decimal("0"))

        projected_group = (
            current + additional_exposure + amount
        )

        projected_total = (
            self.total_exposure + additional_total + amount
        )

        if projected_total <= 0:
            raise ValueError("Exposição total inválida")

        concentration = (
            projected_group / projected_total
        ) * Decimal("100")

        limit = Decimal(str(max_percent))

        return {
            "approved": concentration <= limit,
            "group": key,
            "current_exposure": str(current),
            "projected_exposure": str(projected_group),
            "projected_total": str(projected_total),
            "concentration_percent": str(
                concentration.quantize(Decimal("0.01"))
            ),
            "limit_percent": str(limit),
        }

    def summary(self):
        return {
            "fund_cnpj": self.fund_cnpj,
            "reference_date": self.reference_date.isoformat(),
            "total_rows": self.total_rows,
            "fund_rows": self.fund_rows,
            "total_exposure": str(self.total_exposure),
            "sacado_groups": len(self.sacado_exposure),
            "cedentes": len(self.cedente_exposure),
        }
