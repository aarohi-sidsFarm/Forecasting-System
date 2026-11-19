import unittest

import pandas as pd

from scripts.retrain_check import compare


def _summary(hyd, blr, pnq=10.0):
    return pd.DataFrame({"product_wape_pct": [blr, hyd, pnq]}, index=["BLR", "HYD", "PNQ"])


class RetrainCheckTests(unittest.TestCase):
    def test_candidate_must_beat_live_in_both_hyd_and_blr(self):
        _, passing = compare({
            "live models": _summary(3.8, 5.8),
            "hyd only": _summary(3.5, 6.5),
            "both": _summary(3.6, 5.5, pnq=20.0),
        })
        self.assertEqual(passing, ["both"])

    def test_better_cells_are_bold(self):
        lines, _ = compare({"live models": _summary(3.8, 5.8), "c": _summary(3.5, 6.5)})
        self.assertIn("**3.50%**", lines[-1])
        self.assertIn("| 6.50% |", lines[-1])


if __name__ == "__main__":
    unittest.main()
