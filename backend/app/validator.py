import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from validate_docbr import CNPJ


def normalizar_cnpj(documento):
    return re.sub(r"\D", "", documento)


def normalizar_data(valor):
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return datetime.strptime(valor, "%d/%m/%Y").date()


class DadosInsuficientesError(ValueError):
    """A regra não pode ser avaliada com os dados disponíveis."""


class ContextoValidacao:
    """Base nominal completa fornecida, antes dos filtros de elegibilidade.

    Os recebíveis devem estar convertidos pelo csv_parser. Situações cadastrais
    devem ser f´ornecidas por uma fonte externa, usando o CNPJ completo.
    """

    def __init__(self, recebiveis=(), situacoes_cadastrais=None, data_referencia=None):
        self.data_referencia = normalizar_data(data_referencia or date.today())
        self.situacoes_cadastrais = {
            normalizar_cnpj(cnpj): situacao.strip().upper()
            for cnpj, situacao in (situacoes_cadastrais or {}).items()
            if situacao is not None
        }
        self.total_nominal = Decimal("0")
        self.totais = {
            (campo, agrupamento): defaultdict(Decimal)
            for campo in ("DOC_SACADO", "DOC_CEDENTE")
            for agrupamento in ("CNPJ", "RAIZ_CNPJ")
        }

        for recebivel in recebiveis:
            valor = Decimal(str(recebivel["VALOR_NOMINAL"]))
            if not valor.is_finite() or valor < 0:
                raise ValueError("Valor nominal deve ser finito e não negativo")
            self.total_nominal += valor
            for campo in ("DOC_SACADO", "DOC_CEDENTE"):
                documento = normalizar_cnpj(recebivel[campo])
                # O erro de documento é tratado no comando correspondente.
                if len(documento) != 14:
                    continue
                self.totais[campo, "CNPJ"][documento] += valor
                self.totais[campo, "RAIZ_CNPJ"][documento[:8]] += valor


class FundoHandler:
    code = "FUNDO_VALIDO"

    def __init__(self, fundo):
        self.nome = " ".join(fundo["nome"].split()).casefold()
        self.cnpj = normalizar_cnpj(fundo["cnpj"])

    def corresponde(self, target):
        nome = " ".join((target.get("NOME_FUNDO") or "").split()).casefold()
        cnpj = normalizar_cnpj(target.get("DOC_FUNDO") or "")
        return nome == self.nome and cnpj == self.cnpj

    def data(self, target):
        self.aprovado = self.corresponde(target)

    def executar(self):
        return self.aprovado


class CnpjSacadoHandler:
    def __init__(self, parametros, contexto=None):
        self.code = "CNPJ_SACADO_VALIDO"
        self.cnpj_validator = CNPJ()

    def data(self, target):
        self.cnpj = target["DOC_SACADO"]

    def executar(self):
        return self.cnpj_validator.validate(self.cnpj)


class SituacaoCadastralHandler:
    def __init__(self, parametros, contexto=None):
        self.code = "SITUACAO_CADASTRAL_SACADO"
        self.contexto = contexto if contexto is not None else ContextoValidacao()
        self.situacoes_aceitas = {
            situacao.strip().upper() for situacao in parametros["situacoes_aceitas"]
        }

    def data(self, target):
        self.cnpj = normalizar_cnpj(target["DOC_SACADO"])

    def executar(self):
        situacao = self.contexto.situacoes_cadastrais.get(self.cnpj)
        if not situacao:
            raise DadosInsuficientesError(
                f"Situação cadastral não informada para o CNPJ {self.cnpj}"
            )
        return situacao in self.situacoes_aceitas


class TipoRecebivelHandler:
    def __init__(self, parametros, contexto=None):
        self.code = "TIPO_RECEBIVEL"
        self.valid_types = parametros["tipos_aceitos"]

    def data(self, target):
        self.tipo = target["TIPO_RECEBIVEL"]

    def executar(self):
        return self.tipo in self.valid_types


class ValorMinimoHandler:
    def __init__(self, parametros, contexto=None):
        self.code = "VALOR_MINIMO"
        self.min = Decimal(str(parametros["valor_minimo"]))

    def data(self, target):
        self.value = target["VALOR_NOMINAL"]

    def executar(self):
        return self.value >= self.min


class NaoVencidaHandler:
    def __init__(self, parametros, contexto=None):
        self.code = "NAO_VENCIDA"
        self.contexto = contexto if contexto is not None else ContextoValidacao()

    def data(self, target):
        self.expiration_date = normalizar_data(target["DATA_VENCIMENTO_ORIGINAL"])

    def executar(self):
        return self.expiration_date >= self.contexto.data_referencia


class PrazoMaximoHandler:
    def __init__(self, parametros, contexto=None):
        self.code = "PRAZO_MAXIMO"
        self.max = parametros["prazo_maximo_dias"]

    def data(self, target):
        self.acquisition_date = normalizar_data(target["DATA_AQUISICAO"])
        self.expiration_date = normalizar_data(target["DATA_VENCIMENTO_ORIGINAL"])

    def executar(self):
        return 0 <= (self.expiration_date - self.acquisition_date).days <= self.max


class PrazoMinimoHandler:
    def __init__(self, parametros, contexto=None):
        self.code = "PRAZO_MINIMO"
        self.min = parametros["prazo_minimo_dias"]

    def data(self, target):
        self.acquisition_date = normalizar_data(target["DATA_AQUISICAO"])
        self.expiration_date = normalizar_data(target["DATA_VENCIMENTO_ORIGINAL"])

    def executar(self):
        return (self.expiration_date - self.acquisition_date).days >= self.min


class ConcentracaoMaximaHandler:
    def __init__(self, parametros, contexto=None):
        self.contexto = contexto if contexto is not None else ContextoValidacao()
        self.max = Decimal(str(parametros["percentual_maximo"]))
        self.group_by = parametros.get("agrupamento", "CNPJ")

    def data(self, target):
        documento = normalizar_cnpj(target[self.campo])
        self.documento_valido = len(documento) == 14
        self.chave = documento[:8] if self.group_by == "RAIZ_CNPJ" else documento

    def executar(self):
        if not self.documento_valido:
            raise DadosInsuficientesError(f"{self.campo} deve conter 14 dígitos")
        if self.contexto.total_nominal <= 0:
            raise DadosInsuficientesError(
                "Base de concentração deve ser maior que zero"
            )
        totais = self.contexto.totais[self.campo, self.group_by]
        if self.chave not in totais:
            raise DadosInsuficientesError(
                "Documento não encontrado na base de concentração"
            )
        return totais[self.chave] * 100 <= self.contexto.total_nominal * self.max


class ConcentracaoMaximaSacadoHandler(ConcentracaoMaximaHandler):
    code = "CONCENTRACAO_MAXIMA_SACADO"
    campo = "DOC_SACADO"


class ConcentracaoMaximaCedenteHandler(ConcentracaoMaximaHandler):
    code = "CONCENTRACAO_MAXIMA_CEDENTE"
    campo = "DOC_CEDENTE"


class HandlerFactory:
    handlers = {
        "CNPJ_SACADO_VALIDO": CnpjSacadoHandler,
        "SITUACAO_CADASTRAL_SACADO": SituacaoCadastralHandler,
        "TIPO_RECEBIVEL": TipoRecebivelHandler,
        "VALOR_MINIMO": ValorMinimoHandler,
        "NAO_VENCIDA": NaoVencidaHandler,
        "PRAZO_MAXIMO": PrazoMaximoHandler,
        "PRAZO_MINIMO": PrazoMinimoHandler,
        "CONCENTRACAO_MAXIMA_SACADO": ConcentracaoMaximaSacadoHandler,
        "CONCENTRACAO_MAXIMA_CEDENTE": ConcentracaoMaximaCedenteHandler,
    }

    @classmethod
    def criar(cls, codigo, parametros, contexto=None):
        return cls.handlers[codigo](parametros, contexto)


class Validator:
    def __init__(self, validation_file: dict, contexto=None):
        self.contexto = contexto if contexto is not None else ContextoValidacao()
        self.rules = [FundoHandler(validation_file["fundo"])] + [
            HandlerFactory.criar(regra["codigo"], regra["parametros"], self.contexto)
            for regra in validation_file["validadores"]
            if regra["ativo"]
        ]

    def executar(self, target):
        resultados = []
        for regra in self.rules:
            try:
                regra.data(target)
                resultado = {"codigo": regra.code, "aprovado": regra.executar()}
            except DadosInsuficientesError as exc:
                resultado = {"codigo": regra.code, "aprovado": None, "erro": str(exc)}
            resultados.append(resultado)

        return {
            "aprovado": all(item["aprovado"] is True for item in resultados),
            "resultados": resultados,
        }
