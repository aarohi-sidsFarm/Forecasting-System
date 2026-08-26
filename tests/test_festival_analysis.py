import unittest

import pandas as pd

from ml_pipeline import analyze_festival_exports


class FestivalAnalysisTests(unittest.TestCase):
    def test_golconda_bonalu_alias_matches_calendar_start_label(self):
        self.assertEqual(
            analyze_festival_exports.normalize_festival("Golconda Bonalu"),
            analyze_festival_exports.normalize_festival("Bonalu Festival Begins"),
        )

    def test_day_first_dates_keep_varalakshmi_window_aligned(self):
        daily = analyze_festival_exports.load_daily()
        rows = daily[
            (daily["delivery_year"] == 2025)
            & (daily["festival_name"] == "Varalakshmi Vratam")
            & (daily["city_cd"] == "HYD")
            & (daily["product_name"] == "A2 Buffalo Milk")
        ]
        festival = rows[rows["days_from_festival"] == 0].iloc[0]
        day_before = rows[rows["days_from_festival"] == -1].iloc[0]
        self.assertEqual(festival["festival_date"], pd.Timestamp("2025-08-08"))
        self.assertEqual(festival["delivery_date"], pd.Timestamp("2025-08-08"))
        self.assertEqual(day_before["delivery_date"], pd.Timestamp("2025-08-07"))

    def test_export_uses_reviewed_state_specific_dates(self):
        daily = analyze_festival_exports.load_daily()
        naga = daily[
            (daily["delivery_year"] == 2026)
            & daily["festival_name"].eq("Naga Panchami")
        ]
        self.assertEqual(set(naga["festival_date"]), {pd.Timestamp("2026-08-17")})

        ram_navami = daily[
            (daily["delivery_year"] == 2026)
            & daily["festival_name"].eq("Ram Navami")
        ][["city_cd", "festival_date"]].drop_duplicates()
        self.assertEqual(
            set(ram_navami.itertuples(index=False, name=None)),
            {("BLR", pd.Timestamp("2026-03-26")), ("HYD", pd.Timestamp("2026-03-27"))},
        )

        blr_nagula = daily[
            daily["festival_name"].eq("Nagula Chavithi")
            & daily["city_cd"].eq("BLR")
        ]
        self.assertTrue(blr_nagula.empty)

    def test_all_operating_cities_are_supported(self):
        self.assertEqual(analyze_festival_exports.PRIORITY_CITIES, {"HYD", "VGA", "BLR", "PNQ"})


if __name__ == "__main__":
    unittest.main()
