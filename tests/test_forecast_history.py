import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from backend.forecast_history import (
    export_run,
    import_ledger,
    issued_forecast_for_date,
    issued_run_for_issue_date,
    record_run,
)


def issued_row(issue_date, forecast_date, city, product="Cow Milk", qty=100):
    return {
        "issue_date": issue_date,
        "forecast_date": forecast_date,
        "horizon": (
            pd.Timestamp(forecast_date) - pd.Timestamp(issue_date)
        ).days,
        "city_cd": city,
        "product_name": product,
        "p50_qty": qty,
        "visible_subscription_qty": 60,
        "confirmed_subscription_qty": 50,
        "at_risk_subscription_qty": 10,
        "visible_buy_once_qty": 15,
        "ml_unknown_adhoc_qty": 25,
    }


class ForecastHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "history.db")

    def tearDown(self):
        self.temp_dir.cleanup()

    def record(self, rows):
        return record_run(
            pd.DataFrame(rows),
            run_kind="official_issued",
            model_version="test",
            cutoff_policy="test",
            metadata={"test": True},
            db_path=self.db_path,
        )

    def test_daily_issuance_is_discoverable_and_immutable(self):
        first = self.record([
            issued_row("2026-08-15", "2026-08-18", "BLR"),
        ])
        existing = issued_run_for_issue_date("2026-08-15", self.db_path)
        self.assertEqual(existing["run_id"], first["run_id"])
        with self.assertRaises(sqlite3.IntegrityError):
            self.record([
                issued_row("2026-08-15", "2026-08-18", "BLR", qty=999),
            ])

    def test_failed_row_insert_rolls_back_the_run_header(self):
        duplicate = issued_row("2026-08-15", "2026-08-18", "BLR")
        with self.assertRaises(sqlite3.IntegrityError):
            self.record([duplicate, duplicate])
        connection = sqlite3.connect(self.db_path)
        try:
            runs = connection.execute("SELECT COUNT(*) FROM forecast_runs").fetchone()[0]
            rows = connection.execute("SELECT COUNT(*) FROM forecast_rows").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(runs, 0)
        self.assertEqual(rows, 0)

    def test_target_date_combines_city_rows_from_their_real_issue_dates(self):
        self.record([issued_row("2026-08-15", "2026-08-18", "BLR")])
        self.record([issued_row("2026-08-16", "2026-08-18", "HYD")])
        rows, info = issued_forecast_for_date("2026-08-18", self.db_path)
        self.assertEqual(set(rows["city_cd"]), {"BLR", "HYD"})
        self.assertEqual(set(rows["issue_date"]), {"2026-08-15", "2026-08-16"})
        self.assertEqual(len(info["run_ids"]), 2)
        self.assertEqual(info["run_kind"], "official_issued")

    def test_committed_ledger_rebuilds_a_wiped_database(self):
        ledger = str(Path(self.temp_dir.name) / "ledger")
        first = self.record([issued_row("2026-08-15", "2026-08-18", "BLR")])
        export_run(first["run_id"], ledger, self.db_path)
        self.assertEqual(export_run(first["run_id"], ledger, self.db_path),
                         str(Path(ledger) / "2026-08-15.json"))

        fresh_db = str(Path(self.temp_dir.name) / "fresh.db")
        self.assertEqual(import_ledger(ledger, fresh_db), 1)
        self.assertEqual(import_ledger(ledger, fresh_db), 0)
        rows, info = issued_forecast_for_date("2026-08-18", fresh_db)
        self.assertEqual(info["run_id"], first["run_id"])
        self.assertEqual(rows.iloc[0]["confirmed_subscription_qty"], 50)
        self.assertEqual(
            issued_run_for_issue_date("2026-08-15", fresh_db)["run_id"], first["run_id"]
        )

    def test_ledger_never_overwrites_a_different_run_for_the_same_day(self):
        ledger = str(Path(self.temp_dir.name) / "ledger")
        first = self.record([issued_row("2026-08-15", "2026-08-18", "BLR")])
        export_run(first["run_id"], ledger, self.db_path)

        other_db = str(Path(self.temp_dir.name) / "other.db")
        other = record_run(
            pd.DataFrame([issued_row("2026-08-15", "2026-08-18", "BLR", qty=7)]),
            run_kind="official_issued", model_version="test",
            cutoff_policy="test", db_path=other_db,
        )
        with self.assertRaises(ValueError):
            export_run(other["run_id"], ledger, other_db)
        self.assertEqual(import_ledger(ledger, other_db), 0)
        rows, _ = issued_forecast_for_date("2026-08-18", other_db)
        self.assertEqual(rows.iloc[0]["p50_qty"], 7)


if __name__ == "__main__":
    unittest.main()
