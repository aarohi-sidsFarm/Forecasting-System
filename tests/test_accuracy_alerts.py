import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_forecast_accuracy as check  # noqa: E402


def _ledger(folder: Path, issue_date: str, rows: list[tuple[str, str, float]]) -> None:
    payload = {"run": {}, "rows": [
        {"forecast_date": date, "city_cd": city, "product_name": "Cow Milk", "p50_qty": qty}
        for date, city, qty in rows
    ]}
    (folder / f"{issue_date}.json").write_text(json.dumps(payload), encoding="utf-8")


class AccuracyAlertTests(unittest.TestCase):
    def _table(self, issued, actual):
        with tempfile.TemporaryDirectory() as tmp, patch.object(check, "LEDGER_DIR", Path(tmp)):
            _ledger(Path(tmp), "2026-10-20", issued)
            actuals = pd.DataFrame(actual, columns=["target_date", "city_cd", "total_qty"])
            return check.issued_vs_actual(actuals)

    def test_error_is_forecast_minus_actual_over_actual(self):
        table = self._table([("2026-10-22", "HYD", 110.0)], [("2026-10-22", "HYD", 100.0)])
        self.assertAlmostEqual(table.loc[0, "error_pct"], 10.0)

    def test_two_misses_in_a_row_alert(self):
        table = self._table(
            [("2026-10-22", "HYD", 110.0), ("2026-10-23", "HYD", 92.0)],
            [("2026-10-22", "HYD", 100.0), ("2026-10-23", "HYD", 100.0)],
        )
        alerts = check.find_alerts(table)
        self.assertEqual(len(alerts), 1)
        self.assertIn("HYD", alerts[0])

    def test_single_miss_or_small_city_noise_does_not_alert(self):
        table = self._table(
            [("2026-10-22", "HYD", 110.0), ("2026-10-23", "HYD", 101.0),
             ("2026-10-22", "VGA", 108.0), ("2026-10-23", "VGA", 109.0)],
            [("2026-10-22", "HYD", 100.0), ("2026-10-23", "HYD", 100.0),
             ("2026-10-22", "VGA", 100.0), ("2026-10-23", "VGA", 100.0)],
        )
        self.assertEqual(check.find_alerts(table), [])

    def test_days_without_actuals_are_skipped(self):
        table = self._table([("2026-10-29", "HYD", 100.0)], [("2026-10-22", "HYD", 100.0)])
        self.assertTrue(table.empty)


if __name__ == "__main__":
    unittest.main()
