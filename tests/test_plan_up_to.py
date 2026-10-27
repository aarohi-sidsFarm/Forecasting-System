import unittest
from unittest.mock import patch

import pandas as pd

from backend import main


class PlanUpToTests(unittest.TestCase):
    def test_uses_product_uplift_then_city_then_default(self):
        table = {("HYD", "Cow Milk"): 0.05, ("HYD", "ALL"): 0.08}
        with patch.object(main, "_p80_uplift", table):
            self.assertEqual(main._plan_up_to("HYD", "Cow Milk", 1000), 1050)
            self.assertEqual(main._plan_up_to("HYD", "Curd", 1000), 1080)
            self.assertEqual(main._plan_up_to("XYZ", "Curd", 1000), 1100)

    def test_never_below_forecast(self):
        with patch.object(main, "_p80_uplift", {("PNQ", "Curd"): 0.0}):
            self.assertEqual(main._plan_up_to("PNQ", "Curd", 37), 37)
        self.assertEqual(main._plan_up_to("PNQ", "Curd", 0), 0)

    def test_shipped_table_covers_every_city(self):
        for city in main.FORECAST_LEAD_DAYS:
            self.assertIn((city, "ALL"), main._p80_uplift)
            self.assertGreaterEqual(main._p80_uplift[(city, "ALL")], 0)

    def test_issued_rows_keep_the_stored_p80(self):
        issued = pd.DataFrame([{
            "issue_date": "2026-10-26", "forecast_date": "2026-10-28", "horizon": 2,
            "city_cd": "HYD", "product_name": "Cow Milk", "p50_qty": 1000.0, "p80_qty": 1234.0,
            "visible_subscription_qty": 900.0, "confirmed_subscription_qty": 0.0,
            "at_risk_subscription_qty": 0.0, "visible_buy_once_qty": 10.0,
            "ml_unknown_adhoc_qty": 90.0, "run_id": "r1",
        }])
        frame = main._issued_rows_to_operational_df(issued, pd.Timestamp("2026-10-28"))
        self.assertEqual(int(frame["plan_up_to_qty"].iloc[0]), 1234)


if __name__ == "__main__":
    unittest.main()
