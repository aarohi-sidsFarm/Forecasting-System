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

    def test_target_day_filter_keeps_order_date_indexable(self):
        self.assertIn("toi.order_date >= t.target_date", self.sql)
        self.assertIn(
            "toi.order_date < t.target_date + interval '1 day'", self.sql
        )
        self.assertNotIn("toi.order_date::date", self.sql)

    def test_latest_address_lookup_is_scoped_to_candidate_customers(self):
        self.assertIn("relevant_customers as", self.sql)
        self.assertIn("latest_customer_address as", self.sql)
        self.assertIn("join relevant_customers rc", self.sql)
        self.assertIn("on rc.customer_id = ca.cust_id", self.sql)


if __name__ == "__main__":
    unittest.main()
