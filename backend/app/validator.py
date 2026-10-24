from validate_docbr import CNPJ


class CnpjSacadoHandler:
    def __init__(self):
        self.code = "CNPJ_SACADO_VALIDO"
        self.cnpj_validator = CNPJ()

    def data(self, target):
        self.cnpj = target["DOC_SACADO"]

    def executar(self):
        return self.cnpj_validator.validade(self.cnpj)


class SituacaoCadastralHandler:
    def __init__(self):
        self.code = "SITUACAO_CADASTRAL_SACADO"

    def data(self, target):
        pass

    def executar(self):
        return True


class TipoRecebivelHandler:
    def __init__(self, parametros):
        self.code = "TIPO_RECEBIVEL"
        self.valid_types = parametros["tipos_aceitos"]

    def data(self, target):
        self.tipo = target["TIPO_RECEBIVEL"]

    def executar(self):
        return self.tipo in self.valid_types

class ValorMinimoHandler:
    def __init__(self, parametros):
        self.code = "VALOR_MINIMO"
        self.valid_types = parametros["tipos_aceitos"]

    def data(self, target):
        self.tipo = target["TIPO_RECEBIVEL"]

    def executar(self):
        return self.tipo in self.valid_types

class Validator:
    def __init__(self, validation_file: dict):
        self.rules = []
