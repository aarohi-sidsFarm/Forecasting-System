import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUERY = ROOT / "redash_queries" / "festival_demand_history_bulk.sql"


class FestivalQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = " ".join(QUERY.read_text(encoding="utf-8").split())

    def test_known_stale_2026_dates_are_absent(self):
        self.assertNotIn("('Naga Panchami', '2026-07-29'::date", self.sql)
        self.assertNotIn("('Varalakshmi Vratam', '2026-08-28'::date, 'HYD,BLR'", self.sql)

    def test_state_specific_2026_dates_are_present(self):
        expected = [
            "('Holi', '2026-03-03'::date, 'HYD,VGA,PNQ'",
            "('Holi', '2026-03-04'::date, 'BLR'",
            "('Ram Navami', '2026-03-26'::date, 'BLR,PNQ'",
            "('Ram Navami', '2026-03-27'::date, 'HYD,VGA'",
            "('Naga Panchami', '2026-08-17'::date, 'HYD,VGA,BLR,PNQ'",
            "('Varalakshmi Vratam', '2026-08-21'::date, 'HYD,VGA'",
            "('Varamahalakshmi Vrata','2026-08-28'::date, 'BLR'",
        ]
        for fragment in expected:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.sql)


if __name__ == "__main__":
    unittest.main()
