import copy
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from backend import main


TARGET = pd.Timestamp("2026-09-20")


def _totals() -> pd.Series:
    rows = pd.DataFrame(main.build_as_issued_forecast_rows(TARGET))
    rows = rows[rows.method.isin(main.FORECAST_COMPONENT_METHODS)]
    return rows.groupby("city_cd").predicted_qty.sum()


def _scaled_lookup(after_cutoff: bool) -> dict:
    lookup = copy.deepcopy(main._train_lookup)
    for (city, _), series in lookup.items():
        lead = main.FORECAST_LEAD_DAYS.get(city, 2)
        as_of = np.datetime64(TARGET - pd.Timedelta(days=lead + 1))
        dates = series["dates"]
        mask = dates > as_of if after_cutoff else (
            (dates <= as_of) & (dates > as_of - np.timedelta64(10, "D"))
        )
        quantities = series["qty"].astype(float).copy()
        quantities[mask] *= 10
        series["qty"] = quantities
    return lookup


class AsIssuedForecastTests(unittest.TestCase):
    def test_actuals_after_issue_cutoff_cannot_change_the_forecast(self):
        baseline = _totals()
        with patch.object(main, "_train_lookup", _scaled_lookup(after_cutoff=True)):
            self.assertTrue(_totals().equals(baseline))

    def test_actuals_before_issue_cutoff_still_drive_the_forecast(self):
        baseline = _totals()
        with patch.object(main, "_train_lookup", _scaled_lookup(after_cutoff=False)):
            self.assertFalse(_totals().equals(baseline))

    def test_eligibility_is_a_json_serialisable_bool(self):
        rows = pd.DataFrame([
            {
                "city": city, "product_name": product,
                "forecast_status": "official_issued", "forecast_run_id": "run",
                "forecast_date": "2026-10-01",
                "issue_date": str((pd.Timestamp("2026-10-01") - pd.Timedelta(days=lead)).date()),
                "lead_time_days": lead,
            }
            for city, lead in main.FORECAST_LEAD_DAYS.items()
            for product in main.MILK_EXPORT_PRODUCTS[: main.MIN_ISSUED_PRODUCTS_PER_CITY[city]]
        ])
        eligible = main._is_complete_official_forecast(rows)
        self.assertIs(type(eligible), bool)
        self.assertTrue(eligible)

    def test_cutoff_does_not_leak_into_live_serving(self):
        main.build_as_issued_forecast_rows(TARGET)
        self.assertIsNone(main._HISTORY_AS_OF.get())


if __name__ == "__main__":
    unittest.main()
