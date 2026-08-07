import unittest

import pandas as pd

from backend import main


class OperationalForecastPolicyTests(unittest.TestCase):
    def test_actual_comparison_joins_query_1968_values_by_city_sku(self):
        forecast = pd.DataFrame([{
            "city": "HYD",
            "product_name": "A2 Buffalo Milk",
            "forecast_quantity": 16800,
        }])
        actual = pd.DataFrame([{
            "city_cd": "HYD",
            "product_name": "A2 Buffalo Milk",
            "actual_qty": 17040,
        }])
        result = main._attach_actual_comparison(forecast, actual)
        self.assertTrue(bool(result.iloc[0]["actual_available"]))
        self.assertEqual(int(result.iloc[0]["actual_quantity"]), 17040)
        self.assertEqual(int(result.iloc[0]["difference"]), -240)
        self.assertEqual(float(result.iloc[0]["deviation_pct"]), -1.41)

    def test_query_1968_contract_filters_requested_day_and_maps_columns(self):
        raw = pd.DataFrame([
            {
                "date": "05/08/2026", "city": "HYD",
                "product_name": "A2 Buffalo Milk", "quantity": 100,
                "customer_count": 60, "status": "DELIVERED",
            },
            {
                "date": "06/08/2026", "city": "HYD",
                "product_name": "A2 Buffalo Milk", "quantity": 90,
                "customer_count": 55, "status": "DELIVERED",
            },
            {
                "date": "06/08/2026", "city": "HYD",
                "product_name": "A2 Buffalo Milk", "quantity": 10,
                "customer_count": 5, "status": "REFUNDED",
            },
        ])
        raw["date"] = pd.to_datetime(raw["date"], dayfirst=True).dt.normalize()
        selected = raw[raw["date"] == pd.Timestamp("2026-08-06")].rename(columns={
            "city": "city_cd", "quantity": "actual_qty",
            "customer_count": "actual_orders",
        })
        result = main._process_quantity_rows(
            selected,
            qty_candidates=["actual_qty"],
            order_candidates=["actual_orders"],
        )
        self.assertEqual(int(result.iloc[0]["daily_qty"]), 100)

    def test_subscription_processing_keeps_confirmed_and_at_risk_quantities(self):
        raw = pd.DataFrame([{
            "city_cd": "HYD",
            "product_name": "A2 Buffalo Milk",
            "subscription_type": "daily",
            "expected_qty": 100,
            "confirmed_qty": 60,
            "at_risk_qty": 40,
            "confirmed_orders": 50,
        }])
        result = main._process_quantity_rows(
            raw,
            qty_candidates=["expected_qty", "confirmed_qty"],
            order_candidates=["confirmed_orders"],
            allowed_types={"daily", "alternate", "custom"},
        )
        self.assertEqual(int(result.iloc[0]["daily_qty"]), 100)
        self.assertEqual(int(result.iloc[0]["confirmed_qty"]), 60)
        self.assertEqual(int(result.iloc[0]["at_risk_qty"]), 40)

    def test_hyd_a2_saturday_floor_uses_validated_transition(self):
        forecast, floor, factor = main._apply_hyd_a2_saturday_floor(
            16570,
            "HYD",
            "A2 Buffalo Milk",
            "procurement_final_total",
            {
                "day_of_week": 5,
                "lag_1": 17070,
                "lag_7": 16794,
            },
        )
        self.assertEqual(forecast, 16899)
        self.assertEqual(floor, 16899)
        self.assertGreater(factor, 1)

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

    def test_parsi_new_year_is_scoped_to_pune(self):
        target = pd.Timestamp("2026-08-15")
        self.assertEqual(main._festival_features("PNQ", target)["is_city_festival"], 1)
        self.assertEqual(main._festival_features("BLR", target)["is_city_festival"], 0)

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
