import unittest
from datetime import date

import pandas as pd

from app import (
    DATA_CORTE,
    DashboardError,
    calcular_indicadores_gerais,
    calcular_ingressos,
    classificar_faixa_ocupacao,
    classificar_tipo_venda,
    compute_default_date_range,
    consolidar_por_cidade,
    extract_city_from_item,
    filter_allowed_cities,
    oferta_e_lancamento_duplo,
    payment_method_totals,
    revenue_by_city,
    values_to_dataframe,
)


class ValuesToDataframeTest(unittest.TestCase):
    def test_uses_creation_date_without_category(self) -> None:
        values = [
            ["Data de criacao", "Descricao", "Valor"],
            ["02/07/2026", "Pedido 1", "1.234,56"],
        ]

        dataframe = values_to_dataframe(values)

        self.assertIn("data", dataframe.columns)
        self.assertIn("data_de_criacao", dataframe.columns)
        self.assertNotIn("categoria", dataframe.columns)
        self.assertEqual(pd.Timestamp("2026-07-02"), dataframe.loc[0, "data"])
        self.assertEqual(1234.56, dataframe.loc[0, "valor"])

    def test_requires_creation_date(self) -> None:
        values = [
            ["Data", "Descricao", "Valor"],
            ["01/07/2026", "Pedido 1", "99,90"],
        ]

        with self.assertRaisesRegex(DashboardError, "data_de_criacao"):
            values_to_dataframe(values)

    def test_creation_date_takes_precedence_over_data_column(self) -> None:
        values = [
            ["Data", "Data de criacao", "Descricao", "Valor"],
            ["01/01/2020", "02/07/2026", "Pedido 1", "99,90"],
        ]

        dataframe = values_to_dataframe(values)

        self.assertEqual(pd.Timestamp("2026-07-02"), dataframe.loc[0, "data"])

    def test_derives_cidade_from_item_text(self) -> None:
        values = [
            ["Data de criacao", "Descricao", "Valor", "Item"],
            [
                "02/07/2026",
                "Pedido 1",
                "99,90",
                "03.01.02.023 ACESSOS EXTRAS - TURNE SEVEN SAO PAULO",
            ],
        ]

        dataframe = values_to_dataframe(values)

        self.assertEqual("Sao Paulo", dataframe.loc[0, "cidade"])

    def test_cidade_column_overridden_by_item_derivation(self) -> None:
        values = [
            ["Data de criacao", "Descricao", "Valor", "Item", "Cidade"],
            [
                "02/07/2026",
                "Pedido 1",
                "99,90",
                "03.01.02.023 ACESSOS EXTRAS - TURNE SEVEN SAO PAULO",
                "Cidade Errada",
            ],
        ]

        dataframe = values_to_dataframe(values)

        self.assertEqual("Sao Paulo", dataframe.loc[0, "cidade"])

    def test_keeps_rows_with_non_approved_status_for_courtesy_counts(self) -> None:
        values = [
            ["Data de criacao", "Descricao", "Valor", "Status"],
            ["02/07/2026", "Pedido 1", "99,90", "approved"],
            ["02/07/2026", "Pedido 2", "50,00", "pending"],
        ]

        dataframe = values_to_dataframe(values)

        self.assertEqual(2, len(dataframe))

    def test_keeps_all_rows_when_status_column_missing(self) -> None:
        values = [
            ["Data de criacao", "Descricao", "Valor"],
            ["02/07/2026", "Pedido 1", "99,90"],
            ["02/07/2026", "Pedido 2", "50,00"],
        ]

        dataframe = values_to_dataframe(values)

        self.assertEqual(2, len(dataframe))


class ComputeDefaultDateRangeTest(unittest.TestCase):
    def test_defaults_to_preset_start_when_within_data_range(self) -> None:
        result = compute_default_date_range(date(2026, 1, 1), date(2026, 12, 31))

        self.assertEqual((date(2026, 7, 1), date(2026, 12, 31)), result)

    def test_clamps_to_min_date_when_data_starts_after_preset(self) -> None:
        result = compute_default_date_range(date(2026, 8, 1), date(2026, 12, 31))

        self.assertEqual((date(2026, 8, 1), date(2026, 12, 31)), result)

    def test_falls_back_to_full_range_when_all_data_before_preset(self) -> None:
        result = compute_default_date_range(date(2025, 1, 1), date(2025, 6, 30))

        self.assertEqual((date(2025, 1, 1), date(2025, 6, 30)), result)


class ExtractCityFromItemTest(unittest.TestCase):
    def test_extracts_city_after_turne_seven(self) -> None:
        text = "03.01.02.023 ACESSOS EXTRAS - TURNE SEVEN SAO PAULO"

        self.assertEqual("Sao Paulo", extract_city_from_item(text))

    def test_extracts_city_with_accented_turne(self) -> None:
        text = "03.01.02.023 ACESSOS EXTRAS - TURNE SEVEN RIO DE JANEIRO"

        self.assertEqual("Rio de Janeiro", extract_city_from_item(text))

    def test_returns_none_when_pattern_not_found(self) -> None:
        text = "Produto qualquer sem padrao de turne"

        self.assertIsNone(extract_city_from_item(text))

    def test_returns_none_for_empty_value(self) -> None:
        self.assertIsNone(extract_city_from_item(""))
        self.assertIsNone(extract_city_from_item(None))

    def test_normalizes_common_city_variations(self) -> None:
        self.assertEqual("Sao Paulo", extract_city_from_item("TURNE SEVEN Sao Paulo"))
        self.assertEqual("Rio de Janeiro", extract_city_from_item("TURNE SEVEN Rio de Janiero"))
        self.assertEqual("Belo Horizonte", extract_city_from_item("TURNE SEVEN BELO HORIZONTE"))

    def test_recognizes_all_real_tour_stops_from_the_sheet(self) -> None:
        self.assertEqual("Brasilia", extract_city_from_item("TURNE SEVEN BRASILIA"))
        self.assertEqual("Vitoria", extract_city_from_item("TURNE SEVEN VITORIA"))
        self.assertEqual("Florianopolis", extract_city_from_item("TURNE SEVEN FLORIANOPOLIS"))
        self.assertEqual("Campinas", extract_city_from_item("TURNE SEVEN CAMPINAS"))


class DashboardAggregationTest(unittest.TestCase):
    def setUp(self) -> None:
        values = [
            ["Data de criacao", "Descricao", "Valor", "Status", "Item", "Metodo de Pagamento"],
            [
                "02/07/2026",
                "Pago SP",
                "100,00",
                "approved",
                "TURNE SEVEN SAO PAULO",
                "credit_card",
            ],
            [
                "02/07/2026",
                "Cortesia SP",
                "0,00",
                "pending",
                "TURNE SEVEN SAO PAULO",
                "courtesy",
            ],
            [
                "03/07/2026",
                "Pago RJ",
                "200,00",
                "approved",
                "TURNE SEVEN Rio de Janiero",
                "pix",
            ],
            [
                "03/07/2026",
                "Pendente BH",
                "50,00",
                "pending",
                "TURNE SEVEN BELO HORIZONTE",
                "pix",
            ],
            [
                "03/07/2026",
                "Cidade fora",
                "999,00",
                "approved",
                "TURNE SEVEN CURITIBA",
                "pix",
            ],
        ]
        self.dataframe = filter_allowed_cities(values_to_dataframe(values))

    def test_filters_to_allowed_cities_only(self) -> None:
        self.assertEqual({"Sao Paulo", "Rio de Janeiro", "Belo Horizonte"}, set(self.dataframe["cidade"]))

    def test_builds_general_indicators(self) -> None:
        self.assertEqual(
            {
                "total_vendas": 3,
                "total_ingressos": 3,
                "total_clinicas": 3,
                "receita_total": 300.0,
                "cortesias": 1,
            },
            calcular_indicadores_gerais(self.dataframe),
        )

    def test_consolidates_city_table_and_excludes_cities_without_valid_sales(self) -> None:
        table = consolidar_por_cidade(self.dataframe).set_index("Cidade")

        # Belo Horizonte only has a pending (non-approved, non-zero) row, so it has no
        # valid sale and is dropped entirely from the consolidated table.
        self.assertNotIn("Belo Horizonte", table.index)

        self.assertEqual(2, table.loc["Sao Paulo", "Total de vendas"])
        self.assertEqual(2, table.loc["Sao Paulo", "Total de ingressos"])
        self.assertEqual(1, table.loc["Sao Paulo", "Cortesias"])
        self.assertEqual(2, table.loc["Sao Paulo", "Clinicas unicas"])
        self.assertEqual(100.0, table.loc["Sao Paulo", "Valor total vendido"])

        self.assertEqual(1, table.loc["Rio de Janeiro", "Total de vendas"])
        self.assertEqual(1, table.loc["Rio de Janeiro", "Total de ingressos"])
        self.assertEqual(0, table.loc["Rio de Janeiro", "Cortesias"])
        self.assertEqual(200.0, table.loc["Rio de Janeiro", "Valor total vendido"])

    def test_ranks_revenue_by_city_descending(self) -> None:
        ranking = revenue_by_city(self.dataframe)

        self.assertEqual(["Rio de Janeiro", "Sao Paulo"], list(ranking["Cidade"]))
        self.assertEqual([200.0, 100.0], list(ranking["Receita"]))

    def test_ranks_payment_methods_descending(self) -> None:
        ranking = payment_method_totals(self.dataframe)

        self.assertEqual(["pix", "credit_card"], list(ranking["Metodo de pagamento"]))
        self.assertEqual([200.0, 100.0], list(ranking["Receita"]))


class OfertaLancamentoDuploTest(unittest.TestCase):
    def test_matches_exact_suffix(self) -> None:
        self.assertTrue(oferta_e_lancamento_duplo("Ingresso VIP - LANCAMENTO DUPLO"))

    def test_matches_with_accent_and_extra_spacing(self) -> None:
        self.assertTrue(oferta_e_lancamento_duplo("  Ingresso VIP  -   LANÇAMENTO   DUPLO  "))

    def test_matches_regardless_of_case(self) -> None:
        self.assertTrue(oferta_e_lancamento_duplo("ingresso vip - lancamento duplo"))

    def test_does_not_match_without_suffix(self) -> None:
        self.assertFalse(oferta_e_lancamento_duplo("Ingresso VIP"))

    def test_does_not_match_suffix_in_the_middle(self) -> None:
        self.assertFalse(oferta_e_lancamento_duplo("LANCAMENTO DUPLO - Ingresso VIP"))

    def test_handles_empty_and_none(self) -> None:
        self.assertFalse(oferta_e_lancamento_duplo(""))
        self.assertFalse(oferta_e_lancamento_duplo(None))


class ClassificarTipoVendaTest(unittest.TestCase):
    def _dataframe_with_date(self, data_str: str) -> pd.DataFrame:
        values = [
            ["Data de criacao", "Descricao", "Valor"],
            [data_str, "Pedido", "10,00"],
        ]
        return values_to_dataframe(values)

    def test_day_before_cutoff_is_pre_venda(self) -> None:
        dataframe = self._dataframe_with_date("05/07/2026")

        self.assertEqual("Pre-venda", classificar_tipo_venda(dataframe).iloc[0])

    def test_cutoff_day_itself_is_perpetuo(self) -> None:
        dataframe = self._dataframe_with_date("06/07/2026")

        self.assertEqual(date(2026, 7, 6), DATA_CORTE)
        self.assertEqual("Perpetuo", classificar_tipo_venda(dataframe).iloc[0])

    def test_day_after_cutoff_is_perpetuo(self) -> None:
        dataframe = self._dataframe_with_date("07/07/2026")

        self.assertEqual("Perpetuo", classificar_tipo_venda(dataframe).iloc[0])


class CalcularIngressosTest(unittest.TestCase):
    def test_double_launch_offer_counts_as_two_tickets_but_one_sale(self) -> None:
        values = [
            ["Data de criacao", "Descricao", "Valor", "Status", "Oferta"],
            ["02/07/2026", "Pedido 1", "100,00", "approved", "VIP - LANCAMENTO DUPLO"],
        ]
        dataframe = values_to_dataframe(values)

        self.assertEqual([2], list(calcular_ingressos(dataframe)))
        self.assertEqual(1, len(dataframe))

    def test_regular_offer_counts_as_one_ticket(self) -> None:
        values = [
            ["Data de criacao", "Descricao", "Valor", "Status", "Oferta"],
            ["02/07/2026", "Pedido 1", "100,00", "approved", "VIP"],
        ]
        dataframe = values_to_dataframe(values)

        self.assertEqual([1], list(calcular_ingressos(dataframe)))

    def test_invalid_sale_counts_zero_tickets(self) -> None:
        values = [
            ["Data de criacao", "Descricao", "Valor", "Status", "Oferta"],
            ["02/07/2026", "Pedido 1", "100,00", "pending", "VIP - LANCAMENTO DUPLO"],
        ]
        dataframe = values_to_dataframe(values)

        self.assertEqual([0], list(calcular_ingressos(dataframe)))


class ConsolidarPorCidadeOcupacaoTest(unittest.TestCase):
    def _build_dataframe(self, cidade: str, quantidade_ingressos: int) -> pd.DataFrame:
        rows = [
            [
                "02/07/2026",
                f"Pedido {i}",
                "50,00",
                "approved",
                f"TURNE SEVEN {cidade.upper()}",
            ]
            for i in range(quantidade_ingressos)
        ]
        values = [["Data de criacao", "Descricao", "Valor", "Status", "Item"], *rows]
        return filter_allowed_cities(values_to_dataframe(values))

    def test_maringa_occupancy_matches_expected_percentage(self) -> None:
        dataframe = self._build_dataframe("MARINGA", 25)

        table = consolidar_por_cidade(dataframe)

        self.assertEqual(50.0, table.loc[table["Cidade"] == "Maringa", "% de ocupacao"].iloc[0])

    def test_city_without_registered_capacity_does_not_break_and_shows_dash(self) -> None:
        dataframe = self._build_dataframe("BELO HORIZONTE", 5)

        table = consolidar_por_cidade(dataframe)
        row = table.loc[table["Cidade"] == "Belo Horizonte"].iloc[0]

        self.assertTrue(pd.isna(row["Capacidade"]))
        self.assertIsNone(row["% de ocupacao"])
        self.assertEqual("-", classificar_faixa_ocupacao(row["% de ocupacao"]))


if __name__ == "__main__":
    unittest.main()