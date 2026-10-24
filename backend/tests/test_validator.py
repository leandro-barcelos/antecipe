import json
import tempfile
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from backend.app.config import carregar_configuracao
from backend.app.csv_parser import parse_row
from backend.app.validator import (
    ContextoValidacao,
    DadosInsuficientesError,
    HandlerFactory,
    Validator,
)


CONFIG_PATH = Path(__file__).resolve().parents[1] / "data/validadores_antecipe.json"
CNPJ = "04.252.011/0001-10"
FILIAL = "04.252.011/0002-00"
OUTRO_CNPJ = "11.222.333/0001-81"
HOJE = date(2026, 10, 24)


def titulo(valor="100", sacado=CNPJ, cedente=OUTRO_CNPJ):
    return {
        "DOC_SACADO": sacado,
        "DOC_CEDENTE": cedente,
        "VALOR_NOMINAL": Decimal(valor),
        "TIPO_RECEBIVEL": "Duplicata",
        "DATA_AQUISICAO": HOJE - timedelta(days=180),
        "DATA_VENCIMENTO_ORIGINAL": HOJE,
    }


def executar(handler, recebivel):
    handler.data(recebivel)
    return handler.executar()


class ConfiguracaoTests(unittest.TestCase):
    def carregar_regra(self, codigo, parametros, ativo=True):
        config = {
            "validadores": [
                {"codigo": codigo, "ativo": ativo, "parametros": parametros}
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            return carregar_configuracao(path)

    def test_rejeita_codigo_ativo_desconhecido_ao_carregar(self):
        with self.assertRaisesRegex(ValueError, "Validador não suportado"):
            self.carregar_regra("DESCONHECIDO", {})

    def test_ignora_regras_inativas(self):
        config = self.carregar_regra("DESCONHECIDO", {}, ativo=False)
        self.assertEqual(Validator(config).rules, [])

    def test_rejeita_parametros_de_concentracao_invalidos_ao_carregar(self):
        for codigo in ("CONCENTRACAO_MAXIMA_SACADO", "CONCENTRACAO_MAXIMA_CEDENTE"):
            for limite, agrupamento in (
                (-1, "CNPJ"), (101, "CNPJ"), (10, "NOME"),
                ("NaN", "CNPJ"), ("Infinity", "CNPJ"),
            ):
                with self.subTest(codigo=codigo, limite=limite, agrupamento=agrupamento):
                    with self.assertRaises(ValueError):
                        self.carregar_regra(codigo, {
                            "percentual_maximo": limite,
                            "agrupamento": agrupamento,
                        })

    def test_aceita_limites_de_concentracao_e_agrupamento_padrao(self):
        for limite in (0, 100):
            with self.subTest(limite=limite):
                config = self.carregar_regra(
                    "CONCENTRACAO_MAXIMA_SACADO", {"percentual_maximo": limite}
                )
                self.assertEqual(Validator(config).rules[0].group_by, "CNPJ")


class SituacaoCadastralTests(unittest.TestCase):
    def handler(self, situacoes):
        return HandlerFactory.criar(
            "SITUACAO_CADASTRAL_SACADO",
            {"situacoes_aceitas": ["ATIVA"]},
            ContextoValidacao(situacoes_cadastrais=situacoes),
        )

    def test_normaliza_cnpj_e_situacao(self):
        handler = self.handler({"04252011000110": " ativa "})
        self.assertTrue(executar(handler, titulo()))

    def test_reprova_situacao_nao_aceita(self):
        self.assertFalse(executar(self.handler({CNPJ: "BAIXADA"}), titulo()))

    def test_ausente_nula_ou_vazia_fica_pendente(self):
        for situacoes in ({}, {CNPJ: None}, {CNPJ: " "}):
            with self.subTest(situacoes=situacoes):
                with self.assertRaises(DadosInsuficientesError):
                    executar(self.handler(situacoes), titulo())

    def test_filial_exige_sua_propria_situacao(self):
        with self.assertRaises(DadosInsuficientesError):
            executar(self.handler({CNPJ: "ATIVA"}), titulo(sacado=FILIAL))


class ConcentracaoTests(unittest.TestCase):
    def setUp(self):
        self.recebiveis = [
            titulo("50"),
            titulo("50", sacado=FILIAL),
            titulo("900", sacado=OUTRO_CNPJ, cedente=CNPJ),
        ]
        self.contexto = ContextoValidacao(iter(self.recebiveis))

    def handler(self, limite=10, agrupamento="RAIZ_CNPJ", contexto=None):
        return HandlerFactory.criar(
            "CONCENTRACAO_MAXIMA_SACADO",
            {"percentual_maximo": limite, "agrupamento": agrupamento},
            contexto if contexto is not None else self.contexto,
        )

    def test_soma_filiais_e_aceita_limite_exato(self):
        self.assertEqual(self.contexto.total_nominal, Decimal("1000"))
        handler = self.handler()
        for recebivel in self.recebiveis[:2]:
            self.assertTrue(executar(handler, recebivel))
        self.assertFalse(executar(handler, self.recebiveis[2]))

    def test_cnpj_completo_separa_filiais(self):
        self.assertTrue(executar(self.handler(8, "CNPJ"), self.recebiveis[0]))
        self.assertFalse(executar(self.handler(8), self.recebiveis[0]))

    def test_nao_arredonda_excesso_para_aprovar(self):
        recebiveis = [titulo("100.01"), titulo("899.99", sacado=OUTRO_CNPJ)]
        handler = self.handler(contexto=ContextoValidacao(recebiveis))
        self.assertFalse(executar(handler, recebiveis[0]))

    def test_cedente_usa_seu_documento_e_cnpj_como_padrao(self):
        handler = HandlerFactory.criar(
            "CONCENTRACAO_MAXIMA_CEDENTE", {"percentual_maximo": 10}, self.contexto
        )
        self.assertTrue(executar(handler, self.recebiveis[0]))
        self.assertFalse(executar(handler, self.recebiveis[2]))

    def test_base_vazia_ou_zerada_fica_pendente(self):
        for recebiveis in ([], [titulo("0")]):
            with self.subTest(recebiveis=recebiveis):
                handler = self.handler(contexto=ContextoValidacao(recebiveis))
                with self.assertRaises(DadosInsuficientesError):
                    executar(handler, titulo())

    def test_documento_ausente_na_base_ou_malformado_fica_pendente(self):
        for documento in ("99.999.999/0001-99", "123"):
            with self.subTest(documento=documento):
                with self.assertRaises(DadosInsuficientesError):
                    executar(self.handler(), titulo(sacado=documento))

    def test_documento_ausente_nao_altera_totais_do_contexto(self):
        totais = self.contexto.totais["DOC_SACADO", "RAIZ_CNPJ"]
        antes = dict(totais)
        with self.assertRaises(DadosInsuficientesError):
            executar(self.handler(), titulo(sacado="99.999.999/0001-99"))
        self.assertEqual(dict(totais), antes)

    def test_limite_zero_so_aceita_exposicao_zero(self):
        recebiveis = [titulo("0"), titulo("100", sacado=OUTRO_CNPJ)]
        handler = self.handler(limite=0, contexto=ContextoValidacao(recebiveis))
        self.assertTrue(executar(handler, recebiveis[0]))
        self.assertFalse(executar(handler, recebiveis[1]))


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.config = carregar_configuracao(CONFIG_PATH)

    def test_instancia_somente_regras_ativas_e_executa_com_dados_do_parser(self):
        raw = {
            **titulo(),
            "VALOR_NOMINAL": "100,00",
            "DATA_AQUISICAO": "27/04/2026",
            "DATA_VENCIMENTO_ORIGINAL": "24/10/2026",
        }
        parsed = parse_row((2, raw))
        self.assertEqual(parsed.errors, [])
        contexto = ContextoValidacao(
            [parsed.data], {CNPJ: "ATIVA"}, data_referencia=HOJE
        )
        validator = Validator(self.config, contexto)
        resultado = validator.executar(parsed.data)
        ativos = [r["codigo"] for r in self.config["validadores"] if r["ativo"]]
        self.assertEqual([r.code for r in validator.rules], ativos)
        por_codigo = {r["codigo"]: r for r in resultado["resultados"]}
        for codigo in ativos:
            self.assertIs(
                por_codigo[codigo]["aprovado"],
                codigo != "CONCENTRACAO_MAXIMA_SACADO",
            )
        self.assertFalse(resultado["aprovado"])

    def test_pendencias_nao_aprovam_nem_interrompem_outras_regras(self):
        resultado = Validator(self.config).executar(titulo())
        por_codigo = {r["codigo"]: r for r in resultado["resultados"]}
        for codigo in ("SITUACAO_CADASTRAL_SACADO", "CONCENTRACAO_MAXIMA_SACADO"):
            self.assertIsNone(por_codigo[codigo]["aprovado"])
            self.assertIn("erro", por_codigo[codigo])
        self.assertTrue(por_codigo["CNPJ_SACADO_VALIDO"]["aprovado"])
        self.assertFalse(resultado["aprovado"])

    def test_aprova_quando_todas_as_regras_passam(self):
        self.config["validadores"] = [
            regra for regra in self.config["validadores"]
            if regra["codigo"] != "CONCENTRACAO_MAXIMA_SACADO"
        ]
        contexto = ContextoValidacao(situacoes_cadastrais={CNPJ: "ATIVA"}, data_referencia=HOJE)
        self.assertTrue(Validator(self.config, contexto).executar(titulo())["aprovado"])

    def test_aprova_com_todas_as_regras_ativas_incluindo_concentracao(self):
        recebiveis = [titulo("100"), titulo("900", sacado=OUTRO_CNPJ)]
        contexto = ContextoValidacao(recebiveis, {CNPJ: "ATIVA"}, HOJE)
        validator = Validator(self.config, contexto)
        self.assertTrue(validator.executar(recebiveis[0])["aprovado"])

    def test_prazo_maximo_reprova_vencimento_anterior_a_aquisicao(self):
        recebivel = {**titulo(), "DATA_AQUISICAO": HOJE + timedelta(days=1)}
        handler = HandlerFactory.criar("PRAZO_MAXIMO", {"prazo_maximo_dias": 180})
        self.assertFalse(executar(handler, recebivel))

    def test_cnpj_invalido_reprova(self):
        handler = HandlerFactory.criar("CNPJ_SACADO_VALIDO", {})
        self.assertFalse(executar(handler, titulo(sacado="04.252.011/0001-11")))
        self.assertTrue(executar(handler, titulo()))

    def test_valor_minimo_aceita_limite_exato(self):
        handler = HandlerFactory.criar("VALOR_MINIMO", {"valor_minimo": 100.0})
        self.assertTrue(executar(handler, titulo("100.00")))
        self.assertFalse(executar(handler, titulo("99.99")))

    def test_reuso_do_validator_nao_reutiliza_resultados_do_titulo_anterior(self):
        recebiveis = [titulo("100"), titulo("900", sacado=OUTRO_CNPJ)]
        contexto = ContextoValidacao(recebiveis, {CNPJ: "ATIVA"}, HOJE)
        validator = Validator(self.config, contexto)
        primeiro = validator.executar(recebiveis[0])
        segundo = validator.executar(recebiveis[1])
        self.assertTrue(primeiro["aprovado"])
        self.assertFalse(segundo["aprovado"])
        self.assertIsNone(next(
            regra["aprovado"] for regra in segundo["resultados"]
            if regra["codigo"] == "SITUACAO_CADASTRAL_SACADO"
        ))

    def test_limites_de_datas(self):
        contexto = ContextoValidacao(data_referencia=HOJE)
        for codigo, parametros in (
            ("NAO_VENCIDA", {}),
            ("PRAZO_MAXIMO", {"prazo_maximo_dias": 180}),
            ("PRAZO_MINIMO", {"prazo_minimo_dias": 180}),
        ):
            with self.subTest(codigo=codigo):
                handler = HandlerFactory.criar(codigo, parametros, contexto)
                self.assertTrue(executar(handler, titulo()))
        vencido = {**titulo(), "DATA_VENCIMENTO_ORIGINAL": HOJE - timedelta(days=1)}
        self.assertFalse(executar(HandlerFactory.criar("NAO_VENCIDA", {}, contexto), vencido))
        prazo_longo = {**titulo(), "DATA_AQUISICAO": HOJE - timedelta(days=181)}
        self.assertFalse(executar(HandlerFactory.criar("PRAZO_MAXIMO", {"prazo_maximo_dias": 180}), prazo_longo))
        prazo_curto = {**titulo(), "DATA_AQUISICAO": HOJE - timedelta(days=179)}
        self.assertFalse(executar(HandlerFactory.criar("PRAZO_MINIMO", {"prazo_minimo_dias": 180}), prazo_curto))


if __name__ == "__main__":
    unittest.main()
