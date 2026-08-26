import unittest
from pathlib import Path

import pandas as pd

from scripts.audit_festival_calendar import load_and_validate


ROOT = Path(__file__).resolve().parents[1]
CALENDAR = ROOT / "backend" / "ml_models" / "festival_list_2024_2026.csv"


class FestivalCalendarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calendar, cls.errors = load_and_validate(CALENDAR)

    def test_calendar_is_structurally_valid(self):
        self.assertEqual(self.errors, [])

    def assert_event(self, event_date: str, festival: str, city: str):
        target = pd.Timestamp(event_date)
        rows = self.calendar[
            self.calendar["parsed_date"].eq(target)
            & self.calendar["festival"].eq(festival)
        ]
        self.assertTrue(
            any("ALL" in str(value).split(",") or city in str(value).split(",") for value in rows["cities"]),
            f"Missing {festival} for {city} on {event_date}",
        )

    def test_state_specific_2026_dates(self):
        expected = [
            ("2026-03-26", "Ram Navami", "BLR"),
            ("2026-03-26", "Ram Navami", "PNQ"),
            ("2026-03-27", "Ram Navami", "HYD"),
            ("2026-03-27", "Ram Navami", "VGA"),
            ("2026-08-21", "Varalakshmi Vratam", "HYD"),
            ("2026-08-21", "Varalakshmi Vratam", "VGA"),
            ("2026-08-28", "Varamahalakshmi Vrata", "BLR"),
            ("2026-09-13", "Gowri Habba", "BLR"),
            ("2026-09-18", "Gauri Puja", "PNQ"),
        ]
        for event in expected:
            with self.subTest(event=event):
                self.assert_event(*event)

    def test_bonalu_is_a_window_not_only_the_public_holiday(self):
        for event_date in ("2026-07-16", "2026-07-19", "2026-07-26", "2026-08-02", "2026-08-09", "2026-08-10"):
            rows = self.calendar[
                self.calendar["parsed_date"].eq(pd.Timestamp(event_date))
                & self.calendar["festival"].str.contains("Bonalu")
            ]
            self.assertTrue(any("HYD" in str(value).split(",") for value in rows["cities"]))

    def test_naga_panchami_uses_2026_date(self):
        self.assert_event("2026-08-17", "Naga Panchami", "HYD")
        wrong = self.calendar[
            self.calendar["parsed_date"].eq(pd.Timestamp("2026-07-29"))
            & self.calendar["festival"].eq("Naga Panchami")
        ]
        self.assertTrue(wrong.empty)

    def test_verified_historical_corrections_are_preserved(self):
        expected = [
            ("2024-02-16", "Ratha Saptami", "HYD"),
            ("2024-03-08", "Mahashivratri", "HYD"),
            ("2024-08-16", "Varalakshmi Vratam", "HYD"),
            ("2024-08-16", "Varalakshmi Vratam", "BLR"),
            ("2025-02-04", "Ratha Saptami", "HYD"),
            ("2025-04-30", "Akshaya Tritiya", "HYD"),
            ("2025-08-08", "Varalakshmi Vratam", "HYD"),
            ("2025-08-08", "Varalakshmi Vratam", "BLR"),
        ]
        for event in expected:
            with self.subTest(event=event):
                self.assert_event(*event)

        false_dates = [
            ("2024-02-24", "Maha Shivaratri"),
            ("2025-05-30", "Akshaya Tritiya"),
            ("2026-07-29", "Naga Panchami"),
        ]
        for event_date, festival in false_dates:
            rows = self.calendar[
                self.calendar["parsed_date"].eq(pd.Timestamp(event_date))
                & self.calendar["festival"].eq(festival)
            ]
            self.assertTrue(rows.empty, f"Known false date returned: {festival} {event_date}")


if __name__ == "__main__":
    unittest.main()
