import unittest

import pandas as pd

from backend.data_gaps import fill_gap_days, fill_gap_days_in_lookup, gap_days_in_frame


def _frame(values, start="2026-11-01", city="HYD", product="Cow Milk"):
    dates = pd.date_range(start, periods=len(values), freq="D")
    return pd.DataFrame({
        "target_date": dates, "city_cd": city, "product_name": product, "total_qty": values,
    })


class DataGapTests(unittest.TestCase):
    def test_whole_city_zero_after_normal_week_is_a_gap(self):
        values = [100, 110, 120, 130, 140, 150, 160, 170, 0, 190]
        gaps = gap_days_in_frame(_frame(values))
        self.assertEqual(gaps, {("HYD", pd.Timestamp("2026-11-09"))})

    def test_city_that_has_not_started_selling_is_not_a_gap(self):
        self.assertEqual(gap_days_in_frame(_frame([0, 0, 0, 0, 0, 0, 0, 0, 50, 60])), set())

    def test_one_product_at_zero_is_not_a_gap(self):
        frame = pd.concat([
            _frame([100] * 10),
            _frame([50] * 8 + [0, 0], product="Double Toned"),
        ])
        self.assertEqual(gap_days_in_frame(frame), set())

    def test_gap_is_filled_from_same_weekday_a_week_earlier(self):
        values = [100, 110, 120, 130, 140, 150, 160, 170, 0, 190]
        frame = _frame(values)
        filled = fill_gap_days(frame, gap_days_in_frame(frame))
        nov9 = filled.loc[filled["target_date"] == "2026-11-09", "total_qty"].item()
        self.assertEqual(nov9, 110)  # Nov 2
        self.assertEqual(frame["total_qty"].iloc[8], 0)  # input untouched

    def test_absent_day_in_lookup_is_filled(self):
        lookup = {
            ("HYD", "Cow Milk", day): 100.0 + i
            for i, day in enumerate(pd.date_range("2026-11-01", "2026-11-12"))
            if day != pd.Timestamp("2026-11-09")
        }
        repaired, gaps = fill_gap_days_in_lookup(lookup)
        self.assertEqual(gaps, {("HYD", pd.Timestamp("2026-11-09"))})
        self.assertEqual(repaired[("HYD", "Cow Milk", pd.Timestamp("2026-11-09"))], 101.0)


if __name__ == "__main__":
    unittest.main()
