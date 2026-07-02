import unittest
from datetime import date

import pandas as pd

from app import (
    DashboardError,
    compute_default_date_range,
    extract_city_from_item,
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

        self.assertEqual("SAO PAULO", dataframe.loc[0, "cidade"])

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

        self.assertEqual("SAO PAULO", dataframe.loc[0, "cidade"])

    def test_filters_out_rows_with_non_approved_status(self) -> None:
        values = [
            ["Data de criacao", "Descricao", "Valor", "Status"],
            ["02/07/2026", "Pedido 1", "99,90", "approved"],
            ["02/07/2026", "Pedido 2", "50,00", "pending"],
        ]

        dataframe = values_to_dataframe(values)

        self.assertEqual(1, len(dataframe))
        self.assertEqual("Pedido 1", dataframe.iloc[0]["descricao"])

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

        self.assertEqual("SAO PAULO", extract_city_from_item(text))

    def test_extracts_city_with_accented_turne(self) -> None:
        text = "03.01.02.023 ACESSOS EXTRAS - TURNÊ SEVEN RIO DE JANEIRO"

        self.assertEqual("RIO DE JANEIRO", extract_city_from_item(text))

    def test_returns_none_when_pattern_not_found(self) -> None:
        text = "Produto qualquer sem padrao de turne"

        self.assertIsNone(extract_city_from_item(text))

    def test_returns_none_for_empty_value(self) -> None:
        self.assertIsNone(extract_city_from_item(""))
        self.assertIsNone(extract_city_from_item(None))


if __name__ == "__main__":
    unittest.main()
