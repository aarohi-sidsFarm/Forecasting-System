import unittest

import pandas as pd

from backend.direct_features import RELATIVE_FEATURES, add_relative_features


def _row(scale: float) -> dict:
    return {
        "product_enc": 1, "day_of_week": 2, "is_weekend": 0,
        "last_actual": 980 * scale, "target_lag_7": 1010 * scale, "target_lag_14": 990 * scale,
        "target_lag_21": 1000 * scale, "target_lag_28": 970 * scale,
        "roll_7_mean": 1005 * scale, "roll_14_mean": 998 * scale, "roll_28_mean": 1000 * scale,
        "roll_7_std": 20 * scale, "demand_slope_28d": 1.5 * scale, "same_dow_median": 1000 * scale,
        "trend_ratio_7_28": 1.005, "is_festival": 0, "is_city_festival": 0, "is_pre_festival": 0,
        "is_post_festival": 0, "festival_impact_direction": 0, "lag_7_is_event": 0,
        "lag_14_is_event": 0, "lag_21_is_event": 0, "lag_28_is_event": 0,
    }


class RelativeFeatureTests(unittest.TestCase):
    def test_every_model_input_is_produced(self):
        frame = add_relative_features(pd.DataFrame([_row(1.0)]))
        self.assertEqual([c for c in RELATIVE_FEATURES if c not in frame], [])

    def test_inputs_do_not_depend_on_volume(self):
        # A product selling 10x more with the same shape gets the same inputs,
        # so a tree cannot learn a level from them.
        small = add_relative_features(pd.DataFrame([_row(1.0)]))[RELATIVE_FEATURES]
        large = add_relative_features(pd.DataFrame([_row(10.0)]))[RELATIVE_FEATURES]
        pd.testing.assert_frame_equal(small, large)

    def test_no_calendar_level_inputs(self):
        for column in ("month", "week_of_year", "day_of_month", "roll_28_mean", "target_lag_7"):
            self.assertNotIn(column, RELATIVE_FEATURES)


if __name__ == "__main__":
    unittest.main()
