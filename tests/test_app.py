import unittest

import pandas as pd

from app import DashboardError, values_to_dataframe


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


if __name__ == "__main__":
    unittest.main()
