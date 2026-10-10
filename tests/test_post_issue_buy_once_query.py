import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUERY = ROOT / "redash_queries" / "post_issue_buy_once_arrivals.sql"


class PostIssueBuyOnceQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = QUERY.read_text(encoding="utf-8").lower()

    def test_query_derives_city_specific_issue_dates(self):
        self.assertIn("n.city_cd in ('hyd', 'vga') then 2 else 3", self.sql)
        self.assertIn("as issue_date", self.sql)

    def test_query_keeps_only_post_issue_pre_target_arrivals(self):
        self.assertIn("placed_date > issue_date", self.sql)
        self.assertIn("placed_date < target_date", self.sql)

    def test_query_reports_quantity_lines_and_customers(self):
        self.assertIn("new_buy_once_qty", self.sql)
        self.assertIn("new_buy_once_line_count", self.sql)
        self.assertIn("new_buy_once_customers", self.sql)

    def test_target_day_filter_does_not_cast_order_date(self):
        self.assertIn("toi.order_date >= t.target_date", self.sql)
        self.assertIn(
            "toi.order_date < t.target_date + interval '1 day'", self.sql
        )
        self.assertNotIn("toi.order_date::date", self.sql)


if __name__ == "__main__":
    unittest.main()
