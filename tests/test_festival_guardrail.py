import unittest
from unittest.mock import patch

import pandas as pd

from backend import main


class FestivalGuardrailTests(unittest.TestCase):
    def test_direct_model_rows_keep_festival_uplift(self):
        # 2026-08-11 is a Naga Panchami guardrail day for BLR A2 Buffalo Milk,
        # served by the BLR D-3 direct model.
        target = pd.Timestamp("2026-08-11")
        _, name, factor, _ = main._apply_festival_guardrail(
            1000, "BLR", "A2 Buffalo Milk", target, {}
        )
        self.assertIsNotNone(name)
        self.assertNotEqual(factor, 1.0)
        empty = main._empty_component_df()
        rows = pd.DataFrame(main.build_forecast_for_dates(
            pd.DatetimeIndex([target]), empty, empty, None
        ))
        row = rows[
            rows.method.eq("ml_unknown_adhoc")
            & rows.city_cd.eq("BLR")
            & rows.product_name.eq("A2 Buffalo Milk")
        ].iloc[0]
        self.assertIn("direct", row.prediction_source)
        self.assertEqual(row.festival_guardrail_name, name)
        self.assertEqual(row.festival_guardrail_factor, factor)

    def test_all_festivals_on_a_shared_date_are_kept(self):
        names = main._festival_names_by_city_date[("HYD", pd.Timestamp("2024-09-17"))]
        self.assertIn("Ganesh Visarjan", names)
        self.assertIn("Vishwakarma Puja", names)

    def test_nearest_festival_wins_over_a_farther_one(self):
        target = pd.Timestamp("2026-06-10")
        lookup = {
            ("Near Fest", "HYD", "Curd", 0): 2.0,
            ("Far Fest", "HYD", "Curd", -3): 4.0,
        }
        names = {
            ("HYD", target): ["Near Fest"],
            ("HYD", target + pd.Timedelta(days=3)): ["Far Fest"],
        }
        with patch.object(main, "_festival_guardrail_lookup", lookup), \
                patch.object(main, "_festival_names_by_city_date", names), \
                patch.object(main, "_FESTIVAL_GUARDRAIL_MIN_OFFSET", -7), \
                patch.object(main, "_FESTIVAL_GUARDRAIL_MAX_OFFSET", 7):
            _, name, factor, offset = main._apply_festival_guardrail(
                1000, "HYD", "Curd", target, {}
            )
        self.assertEqual((name, factor, offset), ("Near Fest", 1.02, 0))

    def test_calendar_covers_draft_year_and_flags_it(self):
        self.assertGreaterEqual(main.fest_df["date"].max(), pd.Timestamp("2027-12-01"))
        status = main._festival_status()
        self.assertEqual(status["draft_dates_in_use"]["start_date"], "2027-01-01")


if __name__ == "__main__":
    unittest.main()
