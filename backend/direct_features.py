"""Scale-free inputs for the direct city models.

The direct models predict demand as a multiple of the product's trailing
28-day mean. With raw-quantity inputs (lags, rolling means, slope, month)
the trees can still learn absolute levels and the trend of the weeks they
were trained on, so a retrained model carried September's PNQ ramp and BLR
dip into October. Here every quantity is divided by the same 28-day mean,
and calendar position inputs that let a tree memorise a season's level are
left out, so the model can only learn shapes: weekday pattern, recent
momentum and festival effects.

Used by ml_pipeline/train_city_direct.py --relative-features and by the
backend when an artifact has feature_transform == "relative".
"""

from __future__ import annotations

import numpy as np
import pandas as pd

RELATIVE_FEATURES = [
    "product_enc", "day_of_week", "is_weekend",
    "rel_last_actual", "rel_lag_7", "rel_lag_14", "rel_lag_21", "rel_lag_28",
    "rel_roll_7", "rel_roll_14", "rel_std_7", "rel_slope_28", "rel_same_dow_median",
    "trend_ratio_7_28",
    "is_festival", "is_city_festival", "is_pre_festival", "is_post_festival",
    "festival_impact_direction",
    "lag_7_is_event", "lag_14_is_event", "lag_21_is_event", "lag_28_is_event",
]


def add_relative_features(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    scale = frame["roll_28_mean"].clip(lower=1.0)
    frame["rel_last_actual"] = frame["last_actual"] / scale
    for days in (7, 14, 21, 28):
        frame[f"rel_lag_{days}"] = frame[f"target_lag_{days}"] / scale
    frame["rel_roll_7"] = frame["roll_7_mean"] / scale
    frame["rel_roll_14"] = frame["roll_14_mean"] / scale
    frame["rel_std_7"] = frame["roll_7_std"] / scale
    # Change over 28 days as a share of the level.
    frame["rel_slope_28"] = frame["demand_slope_28d"] * 28 / scale
    frame["rel_same_dow_median"] = frame["same_dow_median"] / scale
    return frame.replace([np.inf, -np.inf], 0.0)
