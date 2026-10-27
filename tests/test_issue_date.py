import unittest

import pandas as pd

from backend import main


class LateIssuanceTests(unittest.TestCase):
    def test_evening_run_issues_for_today(self):
        now = pd.Timestamp("2026-10-26 22:05")
        self.assertEqual(main.default_issue_date(now), pd.Timestamp("2026-10-26"))

    def test_run_delayed_past_midnight_issues_for_previous_evening(self):
        # Runs #3 and #4 started around 03:00 on 27 Oct and tried to issue 27 Oct.
        now = pd.Timestamp("2026-10-27 03:10")
        self.assertEqual(main.default_issue_date(now), pd.Timestamp("2026-10-26"))
        self.assertTrue(main._issue_date_allowed(pd.Timestamp("2026-10-26"), now))

    def test_previous_day_is_rejected_after_noon(self):
        now = pd.Timestamp("2026-10-27 12:30")
        self.assertFalse(main._issue_date_allowed(pd.Timestamp("2026-10-26"), now))
        self.assertTrue(main._issue_date_allowed(pd.Timestamp("2026-10-27"), now))

    def test_future_issue_date_is_rejected(self):
        now = pd.Timestamp("2026-10-27 03:10")
        self.assertFalse(main._issue_date_allowed(pd.Timestamp("2026-10-28"), now))

    def test_today_is_not_issued_before_the_2205_cutoff(self):
        # 27 Oct 2026: a re-run at 10:15 locked that day's forecast 12 hours early.
        self.assertTrue(main.issuance_before_cutoff(pd.Timestamp("2026-10-27"), pd.Timestamp("2026-10-27 10:15")))
        self.assertTrue(main.issuance_before_cutoff(pd.Timestamp("2026-10-27"), pd.Timestamp("2026-10-27 22:04")))
        self.assertFalse(main.issuance_before_cutoff(pd.Timestamp("2026-10-27"), pd.Timestamp("2026-10-27 22:05")))
        self.assertFalse(main.issuance_before_cutoff(pd.Timestamp("2026-10-26"), pd.Timestamp("2026-10-27 03:10")))


if __name__ == "__main__":
    unittest.main()
