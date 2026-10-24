import unittest
from datetime import date, timedelta
from decimal import Decimal

from backend.app.pricing import Precificador, validar_precificacao


CONFIG = {
    "metodo": "DESCONTO_SIMPLES", "taxa_mensal_percentual": 2, "base_dias": 30,
}


def recebivel(valor="1000", prazo=30):
    aquisicao = date(2026, 1, 1)
    return {
        "VALOR_NOMINAL": Decimal(valor),
        "DATA_AQUISICAO": aquisicao,
        "DATA_VENCIMENTO_ORIGINAL": aquisicao + timedelta(days=prazo),
    }


class PricingTests(unittest.TestCase):
    def test_desconto_simples_por_prazo_a_partir_da_aquisicao(self):
        for prazo, desconto, liquido in ((30, "20.00", "980.00"), (45, "30.00", "970.00")):
            with self.subTest(prazo=prazo):
                preco = Precificador(CONFIG).calcular(recebivel(prazo=prazo))
                self.assertEqual(preco.como_dict(), {
                    "valor_nominal": "1000.00", "desconto": desconto,
                    "valor_liquido": liquido, "prazo_dias": prazo,
                })

    def test_arredonda_meio_centavo_para_cima_e_fecha_o_valor(self):
        preco = Precificador(CONFIG).calcular(recebivel("0.25"))
        self.assertEqual(preco.desconto, Decimal("0.01"))
        self.assertEqual(preco.valor_liquido, Decimal("0.24"))
        self.assertEqual(preco.desconto + preco.valor_liquido, preco.valor_nominal)

    def test_prazo_zero_e_taxa_zero_nao_aplicam_desconto(self):
        self.assertEqual(Precificador(CONFIG).calcular(recebivel(prazo=0)).desconto, Decimal("0.00"))
        self.assertEqual(Precificador({**CONFIG, "taxa_mensal_percentual": 0}).calcular(recebivel()).desconto, Decimal("0.00"))

    def test_rejeita_prazo_negativo_e_valor_liquido_negativo(self):
        with self.assertRaises(ValueError):
            Precificador(CONFIG).calcular(recebivel(prazo=-1))
        with self.assertRaises(ValueError):
            Precificador({**CONFIG, "taxa_mensal_percentual": 200}).calcular(recebivel())

    def test_rejeita_configuracao_de_precificacao_invalida(self):
        configs = [None, {}, {**CONFIG, "metodo": "OUTRO"}]
        configs += [{**CONFIG, "taxa_mensal_percentual": value} for value in (-1, None, True, "NaN", "Infinity", "abc")]
        configs += [{**CONFIG, "base_dias": value} for value in (0, -1, True, "30", None)]
        for config in configs:
            with self.subTest(config=config):
                with self.assertRaises(ValueError):
                    validar_precificacao(config)
