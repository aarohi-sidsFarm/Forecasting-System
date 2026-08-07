import unittest

import pandas as pd

from backend import main


class OperationalForecastPolicyTests(unittest.TestCase):
    def test_city_target_dates_follow_required_lead_times(self):
        targets = main._operational_target_dates(pd.Timestamp("2026-08-07"))
        self.assertEqual(targets["HYD"], "2026-08-09")
        self.assertEqual(targets["VGA"], "2026-08-09")
        self.assertEqual(targets["BLR"], "2026-08-10")
        self.assertEqual(targets["PNQ"], "2026-08-10")

    def test_city_issue_dates_are_derived_from_selected_target(self):
        issue_dates = main._target_issue_dates(pd.Timestamp("2026-08-08"))
        self.assertEqual(issue_dates["HYD"], "2026-08-06")
        self.assertEqual(issue_dates["VGA"], "2026-08-06")
        self.assertEqual(issue_dates["BLR"], "2026-08-05")
        self.assertEqual(issue_dates["PNQ"], "2026-08-05")

    def test_bonalu_is_scoped_to_hyderabad(self):
        target = pd.Timestamp("2026-08-10")
        self.assertEqual(main._festival_features("HYD", target)["is_city_festival"], 1)
        self.assertEqual(main._festival_features("BLR", target)["is_city_festival"], 0)
        self.assertEqual(main._festival_features("PNQ", target)["is_city_festival"], 0)

    def test_pune_regional_festival_is_supported(self):
        features = main._festival_features("PNQ", pd.Timestamp("2026-02-19"))
        self.assertEqual(features["is_city_festival"], 1)

    def test_operational_frame_keeps_only_each_citys_due_target(self):
        rows = []
        for forecast_date in ("2026-08-09", "2026-08-10"):
            for city in main.FORECAST_LEAD_DAYS:
                rows.append({
                    "forecast_date": forecast_date,
                    "city_cd": city,
                    "product_name": "Cow Milk",
                    "method": "subscription",
                    "predicted_qty": 100,
                })
        frame = main._forecast_rows_to_operational_df(rows, pd.Timestamp("2026-08-07"))
        actual = set(zip(frame["city"], frame["forecast_date"]))
        self.assertEqual(actual, {
            ("HYD", "2026-08-09"),
            ("VGA", "2026-08-09"),
            ("BLR", "2026-08-10"),
            ("PNQ", "2026-08-10"),
        })

    def test_target_frame_returns_one_selected_date_for_every_city(self):
        rows = [
            {
                "forecast_date": "2026-08-08",
                "city_cd": city,
                "product_name": "Cow Milk",
                "method": "subscription",
                "predicted_qty": 100,
            }
            for city in main.FORECAST_LEAD_DAYS
        ]
        frame = main._forecast_rows_to_operational_df(
            rows, target_date=pd.Timestamp("2026-08-08")
        )
        self.assertEqual(set(frame["forecast_date"]), {"2026-08-08"})
        self.assertEqual(set(frame["city"]), set(main.FORECAST_LEAD_DAYS))
        issue_dates = dict(zip(frame["city"], frame["issue_date"]))
        self.assertEqual(issue_dates["HYD"], "2026-08-06")
        self.assertEqual(issue_dates["BLR"], "2026-08-05")


if __name__ == "__main__":
    unittest.main()
