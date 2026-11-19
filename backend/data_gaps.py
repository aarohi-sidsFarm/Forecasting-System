"""Find and repair days whose sales are missing from the data, not really zero.

The delivery business runs every day, so a city that sold normally all week
and then shows 0 packets for every product on one day almost always means the
day was not loaded (Nov 9 2026 was missing from d2c_order_newfact although the
official revenue query showed a normal day). Reading such a day as real zero
sales breaks the models: the direct models refuse any 28-day window with a
zero in it, and every rolling mean drops.

A data-gap day is a (city, date) where the city's total across all products is
0 (or the date is absent) while the median of its previous 7 days is above 0.
Models see the same product's value from the same weekday a week earlier
(two weeks if that is also a gap); reports leave the day out.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

GAP_LOOKBACK_DAYS = 7
GAP_FILL_OFFSETS = (7, 14, 21)


def find_gap_days(city_daily_totals: dict[str, dict[pd.Timestamp, float]]) -> set[tuple[str, pd.Timestamp]]:
    """Return (city, date) pairs that look like missing data.

    city_daily_totals maps city -> {date: total qty across products}. Dates
    between a city's first and last date that are absent count as 0.
    """
    gaps: set[tuple[str, pd.Timestamp]] = set()
    for city, days in city_daily_totals.items():
        if not days:
            continue
        for date in pd.date_range(min(days), max(days), freq="D"):
            if days.get(date, 0.0) > 0:
                continue
            prior = [
                days.get(date - pd.Timedelta(days=back), 0.0)
                for back in range(1, GAP_LOOKBACK_DAYS + 1)
            ]
            if float(np.median(prior)) > 0:
                gaps.add((city, date))
    return gaps


def gap_days_in_frame(df: pd.DataFrame, qty_col: str = "total_qty") -> set[tuple[str, pd.Timestamp]]:
    if df.empty:
        return set()
    dates = pd.to_datetime(df["target_date"]).dt.normalize()
    totals = df.assign(_d=dates).groupby(["city_cd", "_d"])[qty_col].sum()
    by_city: dict[str, dict[pd.Timestamp, float]] = defaultdict(dict)
    for (city, date), qty in totals.items():
        by_city[city][pd.Timestamp(date)] = float(qty)
    return find_gap_days(by_city)


def fill_gap_days(
    df: pd.DataFrame,
    gaps: set[tuple[str, pd.Timestamp]],
    value_cols: tuple[str, ...] = ("total_qty",),
) -> pd.DataFrame:
    """Copy of df with each gap day's values taken from the same weekday 1-3 weeks back."""
    if df.empty or not gaps:
        return df.copy()
    out = df.copy()
    out["target_date"] = pd.to_datetime(out["target_date"]).dt.normalize()
    cols = [col for col in value_cols if col in out.columns]
    indexed = out.set_index(["city_cd", "product_name", "target_date"])
    source = indexed[cols]
    for city, date in sorted(gaps):
        mask = (out["city_cd"] == city) & (out["target_date"] == date)
        for idx in out.index[mask]:
            product = out.at[idx, "product_name"]
            for back in GAP_FILL_OFFSETS:
                key = (city, product, date - pd.Timedelta(days=back))
                if (city, key[2]) in gaps or key not in source.index:
                    continue
                values = source.loc[key]
                if isinstance(values, pd.DataFrame):
                    values = values.iloc[0]
                for col in cols:
                    out.at[idx, col] = values[col]
                break
    return out


def fill_gap_days_in_lookup(
    lookup: dict[tuple[str, str, pd.Timestamp], float],
    fallback=None,
) -> tuple[dict[tuple[str, str, pd.Timestamp], float], set[tuple[str, pd.Timestamp]]]:
    """Repair a {(city, product, date): qty} lookup in place of missing days.

    fallback(city, product, date) supplies values older than the lookup covers.
    Returns the repaired copy and the gap days found.
    """
    if not lookup:
        return dict(lookup), set()
    by_city: dict[str, dict[pd.Timestamp, float]] = defaultdict(lambda: defaultdict(float))
    products: dict[str, set[str]] = defaultdict(set)
    for (city, product, date), qty in lookup.items():
        by_city[city][date] += float(qty)
        products[city].add(product)
    gaps = find_gap_days(by_city)
    repaired = dict(lookup)
    for city, date in gaps:
        for product in products[city]:
            for back in GAP_FILL_OFFSETS:
                past = date - pd.Timedelta(days=back)
                if (city, past) in gaps:
                    continue
                key = (city, product, past)
                if key in lookup:
                    repaired[(city, product, date)] = float(lookup[key])
                    break
                if fallback is not None:
                    value = fallback(city, product, past)
                    if value is not None:
                        repaired[(city, product, date)] = float(value)
                        break
    return repaired, gaps
