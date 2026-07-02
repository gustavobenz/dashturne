import unittest
from datetime import date

import pandas as pd

from app import (
    DashboardError,
    aggregate_city_ticket_table,
    build_kpis,
    compute_default_date_range,
    extract_city_from_item,
    filter_allowed_cities,
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

    def test_builds_static_kpis(self) -> None:
        self.assertEqual(
            {
                "receita_total": 300.0,
                "ingressos_pagos": 2,
                "cortesias": 1,
            },
            build_kpis(self.dataframe),
        )

    def test_aggregates_city_ticket_table(self) -> None:
        table = aggregate_city_ticket_table(self.dataframe)

        self.assertEqual(
            [
                {"Cidade": "Rio de Janeiro", "Total": 1, "Pago": 1, "Cortesia": 0},
                {"Cidade": "Sao Paulo", "Total": 2, "Pago": 1, "Cortesia": 1},
                {"Cidade": "Belo Horizonte", "Total": 1, "Pago": 0, "Cortesia": 0},
            ],
            table.to_dict("records"),
        )

    def test_ranks_revenue_by_city_descending(self) -> None:
        ranking = revenue_by_city(self.dataframe)

        self.assertEqual(["Rio de Janeiro", "Sao Paulo"], list(ranking["Cidade"]))
        self.assertEqual([200.0, 100.0], list(ranking["Receita"]))

    def test_ranks_payment_methods_descending(self) -> None:
        ranking = payment_method_totals(self.dataframe)

        self.assertEqual(["pix", "credit_card"], list(ranking["Metodo de pagamento"]))
        self.assertEqual([200.0, 100.0], list(ranking["Receita"]))


if __name__ == "__main__":
    unittest.main()