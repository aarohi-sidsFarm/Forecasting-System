import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUERY = ROOT / "redash_queries" / "procurement_final_total_training.sql"


class ProcurementTrainingQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = QUERY.read_text(encoding="utf-8").lower()

    def test_inclusive_date_window_keeps_delivery_date_indexable(self):
        self.assertIn("f.delivery_date >= p.start_date", self.sql)
        self.assertIn(
            "f.delivery_date < p.end_date + interval '1 day'", self.sql
        )
        self.assertNotIn("f.delivery_date::date between", self.sql)

    def test_final_total_remains_aligned_with_official_actuals(self):
        self.assertIn("sum(qty) as final_total_qty", self.sql)
        self.assertIn("d2c_order_newfact", self.sql)
        self.assertNotIn("f.status in", self.sql)


if __name__ == "__main__":
    unittest.main()
