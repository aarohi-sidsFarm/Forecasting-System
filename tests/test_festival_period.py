import unittest

import pandas as pd

from backend import main


class FestivalPeriodTests(unittest.TestCase):
    def tearDown(self):
        main._festival_period_profile_cache.clear()

    def test_holiday_week_lowers_hyd_and_blr(self):
        # Dussehra 2026 week: learned from Dussehra 2025, when HYD/BLR fell 15-25%.
        for city in ("HYD", "BLR"):
            effect, festival, _ = main._festival_period_effect(city, pd.Timestamp("2026-10-18"))
            self.assertLess(effect, -0.10, city)
            self.assertIsNotNone(festival)

    def test_ordinary_day_is_untouched(self):
        for city in main.FORECAST_LEAD_DAYS:
            self.assertEqual(main._festival_period_effect(city, pd.Timestamp("2026-07-08"))[0], 0.0)

    def test_effect_is_bounded(self):
        for city in main.FORECAST_LEAD_DAYS:
            for day in pd.date_range("2026-10-01", "2027-01-31"):
                self.assertLessEqual(abs(main._festival_period_effect(city, day)[0]),
                                     main.FESTIVAL_PERIOD_MAX_EFFECT)

    def test_as_of_cutoff_hides_unfinished_occurrences(self):
        # Before Dussehra 2025's window and baseline had completed, nothing
        # can be learned about it, so the 2026 holiday week is not adjusted.
        token = main._HISTORY_AS_OF.set(pd.Timestamp("2025-11-01"))
        try:
            effect, _, _ = main._festival_period_effect("HYD", pd.Timestamp("2026-10-18"))
        finally:
            main._HISTORY_AS_OF.reset(token)
        self.assertEqual(effect, 0.0)

    def test_one_day_spike_is_kept(self):
        # Ganesh Chaturthi 2026 as issued (D-2): HYD jumped 22% on Ganesh 2025.
        token = main._HISTORY_AS_OF.set(pd.Timestamp("2026-09-11"))
        try:
            effect, festival, offset = main._festival_period_effect("HYD", pd.Timestamp("2026-09-14"))
            day_after, _, _ = main._festival_period_effect("HYD", pd.Timestamp("2026-09-16"))
        finally:
            main._HISTORY_AS_OF.reset(token)
        self.assertGreater(effect, 0.12)
        self.assertEqual((festival, offset), ("Ganesh Chaturthi", 0))
        self.assertEqual(day_after, 0.0)

    def test_guardrail_reports_the_period_adjustment(self):
        adjusted, name, factor, _ = main._apply_festival_guardrail(
            10000, "HYD", "A2 Buffalo Milk", pd.Timestamp("2026-10-18"), {}
        )
        self.assertIn("(period)", name)
        self.assertLess(factor, 1.0)
        self.assertEqual(adjusted, round(10000 * factor))


if __name__ == "__main__":
    unittest.main()
