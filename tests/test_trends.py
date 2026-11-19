import unittest
from unittest.mock import patch

import pandas as pd

from backend import main


def _history(rows):
    frame = pd.DataFrame(rows, columns=["target_date", "city_cd", "product_name", "total_qty"])
    frame["target_date"] = pd.to_datetime(frame["target_date"])
    frame["final_subscription_qty"] = frame["total_qty"] * 0.9
    frame["final_buy_once_qty"] = frame["total_qty"] * 0.1
    frame["total_orders"] = frame["total_qty"] // 2
    return frame


def _days(start, count):
    return [str(day.date()) for day in pd.date_range(start, periods=count, freq="D")]


class TrendsTests(unittest.TestCase):
    def setUp(self):
        rows = []
        for day in _days("2026-10-01", 40):
            rows.append((day, "HYD", "Cow Milk", 1000))
            rows.append((day, "BLR", "Cow Milk", 200))
            # Double Toned stops selling from Oct 31.
            rows.append((day, "HYD", "Double Toned", 500 if day < "2026-10-31" else 0))
        self.history = _history(rows)

    def payload(self, issued, city="ALL", product="ALL", gaps=frozenset()):
        with patch.object(main, "_train_df", self.history), \
                patch.object(main, "_DATA_GAP_DAYS", set(gaps)), \
                patch.object(main, "issued_forecasts_between", return_value=issued):
            return main._trends_payload(
                pd.Timestamp("2026-10-25"), pd.Timestamp("2026-11-09"), city, product,
            )

    def test_forecast_total_needs_every_city_issued(self):
        issued = pd.DataFrame([
            ("2026-10-26", "HYD", "Cow Milk", 1100.0, "2026-10-24"),
            ("2026-10-27", "HYD", "Cow Milk", 900.0, "2026-10-25"),
            ("2026-10-27", "BLR", "Cow Milk", 220.0, "2026-10-24"),
        ], columns=["forecast_date", "city_cd", "product_name", "p50_qty", "issue_date"])
        days = {row["date"]: row for row in self.payload(issued)["days"]}
        # Only HYD was issued on the 26th, so no comparable total...
        self.assertIsNone(days["2026-10-26"]["forecast"])
        # ...but its product-level error still counts.
        self.assertEqual(days["2026-10-26"]["abs_error"], 100)
        self.assertEqual(days["2026-10-27"]["forecast"], 1120)
        self.assertEqual(days["2026-10-27"]["abs_error"], 120)

    def test_summary_error_and_bias(self):
        issued = pd.DataFrame([
            ("2026-10-27", "HYD", "Cow Milk", 1100.0, "2026-10-25"),
            ("2026-10-28", "HYD", "Cow Milk", 950.0, "2026-10-26"),
        ], columns=["forecast_date", "city_cd", "product_name", "p50_qty", "issue_date"])
        summary = self.payload(issued, city="HYD", product="Cow Milk")["summary"]
        self.assertEqual(summary["compared_days"], 2)
        self.assertEqual(summary["error_pct"], 7.5)
        self.assertEqual(summary["bias_pct"], 2.5)

    def test_reports_a_product_that_stopped_selling(self):
        events = self.payload(pd.DataFrame(), city="HYD")["events"]
        self.assertEqual(events, [{
            "type": "stopped", "city": "HYD", "product": "Double Toned",
            "date": "2026-10-31", "avg_per_day": 500.0,
        }])

    def test_breakdown_is_by_city_then_by_product(self):
        self.assertEqual(self.payload(pd.DataFrame())["breakdown_by"], "city")
        payload = self.payload(pd.DataFrame(), city="HYD")
        self.assertEqual(payload["breakdown_by"], "product")
        self.assertEqual([row["key"] for row in payload["breakdown"]], ["Cow Milk", "Double Toned"])

    def test_missing_data_day_is_left_out(self):
        gap = pd.Timestamp("2026-11-01")
        self.history.loc[self.history["target_date"] == gap, "total_qty"] = 0
        issued = pd.DataFrame([
            ("2026-11-01", "HYD", "Cow Milk", 1000.0, "2026-10-30"),
            ("2026-11-01", "BLR", "Cow Milk", 200.0, "2026-10-29"),
        ], columns=["forecast_date", "city_cd", "product_name", "p50_qty", "issue_date"])
        payload = self.payload(issued, gaps={("HYD", gap), ("BLR", gap)})
        day = {row["date"]: row for row in payload["days"]}["2026-11-01"]
        self.assertIsNone(day["actual"])
        self.assertIsNone(day["forecast"])
        self.assertEqual(day["missing_data_cities"], ["BLR", "HYD"])
        self.assertEqual(payload["summary"]["compared_days"], 0)
        self.assertEqual(payload["summary"]["missing_data_days"], ["2026-11-01"])
        # 15 of the 16 days have data; the average ignores the missing one.
        self.assertEqual(payload["summary"]["days_with_sales"], 15)

    def test_previous_period_matches_the_days_with_sales(self):
        # History ends Nov 9; asking to Dec 7 must still compare 16 with 16 days.
        with patch.object(main, "_train_df", self.history),                 patch.object(main, "_DATA_GAP_DAYS", set()),                 patch.object(main, "issued_forecasts_between", return_value=pd.DataFrame()):
            summary = main._trends_payload(
                pd.Timestamp("2026-10-25"), pd.Timestamp("2026-12-07"), "ALL", "ALL",
            )["summary"]
        self.assertEqual(summary["prev_start"], "2026-10-09")
        self.assertEqual(summary["prev_end"], "2026-10-24")
        self.assertEqual(summary["compared_through"], "2026-11-09")


if __name__ == "__main__":
    unittest.main()
