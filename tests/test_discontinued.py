import unittest

import pandas as pd

from backend import main


class DiscontinuedSeriesTests(unittest.TestCase):
    def test_pnq_products_that_stopped_selling_are_flagged(self):
        self.assertTrue(main._series_discontinued("PNQ", "Double Toned A2 Buffalo Milk"))
        self.assertTrue(main._series_discontinued("PNQ", "Skim Milk"))

    def test_selling_series_is_not_flagged(self):
        self.assertFalse(main._series_discontinued("HYD", "A2 Buffalo Milk"))
        self.assertFalse(main._series_discontinued("PNQ", "Cow Milk"))

    def test_recent_sale_reactivates_a_series(self):
        latest = pd.Timestamp(main._train_df["target_date"].max()).normalize()
        recent = {("PNQ", "Skim Milk", latest): 12.0}
        self.assertFalse(main._series_discontinued("PNQ", "Skim Milk", recent))

    def test_as_issued_history_cutoff_is_respected(self):
        # PNQ Skim Milk last sold on 23 Mar 2026, so on 1 Mar it was active.
        token = main._HISTORY_AS_OF.set(pd.Timestamp("2026-03-01"))
        try:
            flagged = main._series_discontinued("PNQ", "Skim Milk")
        finally:
            main._HISTORY_AS_OF.reset(token)
        self.assertFalse(flagged)


if __name__ == "__main__":
    unittest.main()
