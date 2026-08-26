import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUERY = ROOT / "redash_queries" / "known_buy_once.sql"


class KnownBuyOnceQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = QUERY.read_text(encoding="utf-8").lower()

    def test_query_applies_city_specific_issue_cutoff(self):
        self.assertIn("toi.created_at at time zone 'asia/kolkata'", self.sql)
        self.assertIn("in ('hyd', 'vga') then 2", self.sql)
        self.assertIn("in ('blr', 'pnq') then 3", self.sql)
        self.assertIn("time '22:05'", self.sql)

    def test_city_and_purchase_type_aliases_are_normalized(self):
        self.assertIn("'blr', 'bangalore', 'bengaluru', 'cam'", self.sql)
        self.assertIn("'buy once', 'adhoc buy once', 'first_x_order'", self.sql)


if __name__ == "__main__":
    unittest.main()
