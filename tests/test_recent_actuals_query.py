import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUERY = ROOT / "redash_queries" / "recent_final_total_actuals.sql"


class RecentActualsQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = QUERY.read_text(encoding="utf-8").lower()

    def test_recent_lags_use_the_all_status_business_target(self):
        self.assertIn("recent final all-status total packet demand", self.sql)
        self.assertNotIn("f.status in", self.sql)

    def test_recent_date_range_does_not_cast_the_filtered_column(self):
        self.assertIn(
            "f.delivery_date >= t.target_date - interval '90 days'", self.sql
        )
        self.assertIn(
            "f.delivery_date < t.target_date + interval '1 day'", self.sql
        )
        self.assertNotIn("f.delivery_date::date >=", self.sql)

    def test_target_date_includes_latest_completed_lag_day(self):
        self.assertIn("through the latest completed day", self.sql)


if __name__ == "__main__":
    unittest.main()
