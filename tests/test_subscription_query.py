import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUERY = ROOT / "redash_queries" / "subscription_forecast.sql"


class SubscriptionQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = QUERY.read_text(encoding="utf-8").lower()

    def test_pause_filter_is_evaluated_for_target_date(self):
        self.assertNotIn("coalesce(s.is_paused, false) = false", self.sql)
        self.assertIn("s.pause_end_date::date >= t.target_date", self.sql)

    def test_missing_price_is_not_silently_wallet_confirmed(self):
        self.assertIn("wallet_unknown_qty", self.sql)
        self.assertIn("ct.has_missing_price", self.sql)
        self.assertIn("c.current_balance is null", self.sql)
        self.assertIn("when c.id is null", self.sql)

    def test_start_date_is_used_when_valid_from_is_missing(self):
        self.assertIn("coalesce(s.valid_from, s.start_date)::date <= t.target_date", self.sql)

    def test_city_and_address_fallbacks_are_deterministic(self):
        self.assertIn("'blr', 'bangalore', 'bengaluru', 'cam'", self.sql)
        self.assertIn("updated_at desc nulls last, id desc", self.sql)

    def test_query_is_scoped_to_operational_products(self):
        self.assertIn("'double toned a2 buffalo milk'", self.sql)
        self.assertIn("'double toned milk'", self.sql)

    def test_final_result_does_not_split_distinct_customers_by_subscription_type(self):
        final_select = self.sql.split("select", maxsplit=1)[-1]
        self.assertNotIn("r.subscription_type,", final_select)


if __name__ == "__main__":
    unittest.main()
