import copy
import unittest
from unittest.mock import AsyncMock, patch

import pandas as pd

from backend import main


class OperationalForecastPolicyTests(unittest.TestCase):
    def test_normal_sunday_has_no_festival_bleed(self):
        target = pd.Timestamp("2026-08-30")
        for city in ("HYD", "BLR"):
            features = main._festival_features(city, target)
            self.assertEqual(features, {
                "is_festival": 0,
                "is_city_festival": 0,
                "is_pre_festival": 0,
                "is_post_festival": 0,
                "festival_impact_direction": 0,
            })

    def test_lag_provenance_identifies_recursive_prediction(self):
        target = pd.Timestamp("2026-08-25")
        recursive_date = target - pd.Timedelta(days=1)
        features = main._get_lag_features(
            "BLR",
            "Cow Milk",
            target,
            future_preds={("BLR", "Cow Milk", recursive_date): 9999},
            recent_actuals={},
        )
        self.assertEqual(features["lag_1_source"], "recursive_prediction")
        self.assertEqual(features["recursive_days_in_roll_7"], 1)

    def test_status_reports_remembered_redash_failure_as_degraded(self):
        previous = dict(main._redash_health)
        try:
            main._redash_health.update({
                "last_success": None,
                "last_failure": "2026-08-25T10:00:00+05:30",
                "last_error": "subscription 2026-08-25: timeout",
            })
            result = main.status()
            self.assertEqual(result["status"], "degraded")
            self.assertEqual(result["redash"]["state"], "degraded")
        finally:
            main._redash_health.clear()
            main._redash_health.update(previous)

    def test_successful_query_does_not_hide_another_query_failure(self):
        previous = copy.deepcopy(main._redash_health)
        try:
            main._redash_health.clear()
            main._redash_health.update({
                "last_success": None,
                "last_failure": None,
                "last_error": None,
                "queries": {},
            })
            main._redash_health_event(
                "subscription",
                3085,
                "failed",
                target_date="2026-08-26",
                error="timeout",
            )
            main._redash_health_event(
                "recent_actuals",
                3269,
                "healthy",
                target_date="2026-08-26",
            )
            result = main.status()
            self.assertEqual(result["redash"]["state"], "degraded")
            self.assertIn("subscription", result["redash"]["last_error"])
            self.assertIsNone(
                result["redash"]["queries"]["recent_actuals"]["last_error"]
            )
        finally:
            main._redash_health.clear()
            main._redash_health.update(previous)

    def test_blr_d3_direct_ignores_actuals_after_completed_cutoff(self):
        # Keep the fixture inside the bundled training window. In production,
        # dates after that window are supplied by the recent-actuals query.
        target = pd.Timestamp("2026-08-19")
        baseline = main._predict_blr_d3_direct("Cow Milk", target, {})
        future_only = {
            ("BLR", "Cow Milk", pd.Timestamp("2026-08-16")): 999999,
            ("BLR", "Cow Milk", pd.Timestamp("2026-08-18")): 999999,
        }
        with_future = main._predict_blr_d3_direct(
            "Cow Milk", target, future_only
        )
        self.assertIsNotNone(baseline)
        self.assertEqual(baseline, with_future)
        self.assertTrue(baseline[1].startswith("blr_d3_direct:"))

    def test_hyd_d2_direct_ignores_actuals_after_completed_cutoff(self):
        target = pd.Timestamp("2026-08-19")
        baseline = main._predict_hyd_d2_direct("Cow Milk", target, {})
        future_only = {
            ("HYD", "Cow Milk", pd.Timestamp("2026-08-17")): 999999,
            ("HYD", "Cow Milk", pd.Timestamp("2026-08-18")): 999999,
        }
        with_future = main._predict_hyd_d2_direct(
            "Cow Milk", target, future_only
        )
        self.assertIsNotNone(baseline)
        self.assertEqual(baseline, with_future)
        self.assertTrue(baseline[1].startswith("hyd_d2_direct:"))

    def test_hyd_focus_model_only_replaces_configured_products(self):
        previous_base = main._hyd_d2_direct
        previous_focus = main._hyd_d2_focus_direct
        main._hyd_d2_direct = {"name": "base"}
        main._hyd_d2_focus_direct = {
            "name": "focus",
            "product_encoder": type("Encoder", (), {
                "classes_": ["A2 Buffalo Milk", "Cow Milk", "Toned Milk"],
            })(),
        }
        try:
            with patch.object(
                main,
                "_predict_city_direct",
                side_effect=lambda artifact, *_args: (artifact["name"], "method"),
            ):
                focused = main._predict_hyd_d2_direct(
                    "Cow Milk", pd.Timestamp("2026-10-10"), {}
                )
                unchanged = main._predict_hyd_d2_direct(
                    "Curd", pd.Timestamp("2026-10-10"), {}
                )
            self.assertEqual(focused[0], "focus")
            self.assertEqual(unchanged[0], "base")
        finally:
            main._hyd_d2_direct = previous_base
            main._hyd_d2_focus_direct = previous_focus

    def test_hyd_focus_model_is_fresh_and_limited_to_requested_products(self):
        self.assertIsNotNone(main._hyd_d2_focus_direct)
        focus = main._hyd_d2_focus_direct
        self.assertEqual(
            set(focus["product_encoder"].classes_),
            {"A2 Buffalo Milk", "Cow Milk", "Toned Milk"},
        )
        # Training data is refreshed weekly without retraining, so the model
        # may trail the data; flag it only once it is badly out of date.
        lag_days = (main._train_df["target_date"].max() - pd.Timestamp(focus["trained_through"])).days
        self.assertGreaterEqual(lag_days, 0)
        self.assertLessEqual(lag_days, 45)

    def test_actual_comparison_joins_query_1968_values_by_city_sku(self):
        forecast = pd.DataFrame([{
            "city": "HYD",
            "product_name": "A2 Buffalo Milk",
            "forecast_quantity": 16800,
        }])
        actual = pd.DataFrame([{
            "city_cd": "HYD",
            "product_name": "A2 Buffalo Milk",
            "actual_qty": 17040,
        }])
        result = main._attach_actual_comparison(forecast, actual)
        self.assertTrue(bool(result.iloc[0]["actual_available"]))
        self.assertEqual(int(result.iloc[0]["actual_quantity"]), 17040)
        self.assertEqual(int(result.iloc[0]["difference"]), -240)
        self.assertEqual(float(result.iloc[0]["deviation_pct"]), -1.41)
        self.assertEqual(float(result.iloc[0]["absolute_error_pct"]), 1.41)

    def test_city_aliases_are_normalized_before_grouping(self):
        raw = pd.DataFrame([
            {"city_cd": "cam", "product_name": "Toned Milk", "quantity": 10},
            {"city_cd": "Bengaluru", "product_name": "Toned Milk", "quantity": 5},
        ])
        result = main._process_quantity_rows(
            raw,
            qty_candidates=["quantity"],
            order_candidates=[],
        )
        self.assertEqual(result.iloc[0]["city_cd"], "BLR")
        self.assertEqual(int(result.iloc[0]["daily_qty"]), 15)

    def test_only_complete_immutable_forecast_is_comparison_eligible(self):
        target_date = pd.Timestamp("2026-08-20")
        rows = []
        for city, lead_days in main.FORECAST_LEAD_DAYS.items():
            for product in main.MILK_EXPORT_PRODUCTS:
                rows.append({
                    "city": city,
                    "product_name": product,
                    "forecast_status": "official_issued",
                    "forecast_run_id": f"run-{city}",
                    "issue_date": str((target_date - pd.Timedelta(days=lead_days)).date()),
                    "forecast_date": str(target_date.date()),
                    "lead_time_days": lead_days,
                })
        official = pd.DataFrame(rows)
        self.assertTrue(main._is_complete_official_forecast(official))
        official.loc[official["city"] == "BLR", "forecast_status"] = "live_preview"
        self.assertFalse(main._is_complete_official_forecast(official))

    def test_query_1968_month_extract_preserves_dates_and_maps_columns(self):
        raw = pd.DataFrame([
            {
                "date": "05/08/2026", "city": "HYD",
                "product_name": "A2 Buffalo Milk", "quantity": 100,
                "customer_count": 60, "status": "DELIVERED",
            },
            {
                "date": "06/08/2026", "city": "HYD",
                "product_name": "A2 Buffalo Milk", "quantity": 90,
                "customer_count": 55, "status": "DELIVERED",
            },
            {
                "date": "06/08/2026", "city": "HYD",
                "product_name": "A2 Buffalo Milk", "quantity": 10,
                "customer_count": 5, "status": "REFUNDED",
            },
        ])
        result = main._process_selected_actuals_period(raw)
        self.assertEqual(set(result["forecast_date"]), {
            pd.Timestamp("2026-08-05"), pd.Timestamp("2026-08-06")
        })
        selected = result[result["forecast_date"] == pd.Timestamp("2026-08-06")]
        self.assertEqual(int(selected.iloc[0]["actual_qty"]), 100)
        self.assertEqual(int(selected.iloc[0]["actual_orders"]), 60)

    def test_subscription_processing_uses_confirmed_as_procurement_floor(self):
        raw = pd.DataFrame([{
            "city_cd": "HYD",
            "product_name": "A2 Buffalo Milk",
            "subscription_type": "daily",
            "expected_qty": 100,
            "confirmed_qty": 60,
            "at_risk_qty": 30,
            "wallet_unknown_qty": 10,
            "confirmed_orders": 50,
        }])
        result = main._process_quantity_rows(
            raw,
            qty_candidates=["confirmed_qty", "expected_qty"],
            order_candidates=["confirmed_orders"],
            allowed_types={"daily", "alternate", "custom"},
        )
        self.assertEqual(int(result.iloc[0]["daily_qty"]), 60)
        self.assertEqual(int(result.iloc[0]["confirmed_qty"]), 60)
        self.assertEqual(int(result.iloc[0]["at_risk_qty"]), 30)
        self.assertEqual(int(result.iloc[0]["wallet_unknown_qty"]), 10)
        self.assertEqual(int(result.iloc[0]["unconfirmed_qty"]), 40)

    def test_normal_target_knows_when_its_d7_lag_was_a_festival(self):
        features = main._build_model_features(
            "HYD", "Cow Milk", pd.Timestamp("2026-08-24"), True, {}, {}
        )
        self.assertEqual(features["is_festival"], 0)
        self.assertEqual(features["is_city_festival"], 0)
        self.assertEqual(features["lag_7_is_event"], 1)

    def test_city_target_dates_follow_required_lead_times(self):
        targets = main._operational_target_dates(pd.Timestamp("2026-08-07"))
        self.assertEqual(targets["HYD"], "2026-08-09")
        self.assertEqual(targets["VGA"], "2026-08-09")
        self.assertEqual(targets["BLR"], "2026-08-10")
        self.assertEqual(targets["PNQ"], "2026-08-10")

    def test_city_issue_dates_are_derived_from_selected_target(self):
        issue_dates = main._target_issue_dates(pd.Timestamp("2026-08-08"))
        self.assertEqual(issue_dates["HYD"], "2026-08-06")
        self.assertEqual(issue_dates["VGA"], "2026-08-06")
        self.assertEqual(issue_dates["BLR"], "2026-08-05")
        self.assertEqual(issue_dates["PNQ"], "2026-08-05")

    def test_bonalu_is_scoped_to_hyderabad(self):
        target = pd.Timestamp("2026-08-10")
        self.assertEqual(main._festival_features("HYD", target)["is_city_festival"], 1)
        self.assertEqual(main._festival_features("BLR", target)["is_city_festival"], 0)
        self.assertEqual(main._festival_features("PNQ", target)["is_city_festival"], 0)

    def test_varalakshmi_uses_conservative_hyd_sku_overrides(self):
        target = pd.Timestamp("2026-08-21")
        features = main._festival_features("HYD", target)
        cow = main._apply_festival_guardrail(
            1000, "HYD", "Cow Milk", target, features
        )
        buffalo = main._apply_festival_guardrail(
            1000, "HYD", "A2 Buffalo Milk", target, features
        )
        self.assertEqual(cow, (1100, "Varalakshmi Vratam", 1.1, 0))
        self.assertEqual(buffalo, (1080, "Varalakshmi Vratam", 1.08, 0))

    def test_varalakshmi_hyd_date_does_not_adjust_blr(self):
        target = pd.Timestamp("2026-08-21")
        features = main._festival_features("BLR", target)
        result = main._apply_festival_guardrail(
            1000, "BLR", "Cow Milk", target, features
        )
        self.assertEqual(result, (1000, None, 1.0, 0))

    def test_varalakshmi_vga_uses_regional_proxy(self):
        target = pd.Timestamp("2026-08-21")
        features = main._festival_features("VGA", target)
        result = main._apply_festival_guardrail(
            1000, "VGA", "Cow Milk", target, features
        )
        self.assertEqual(result, (1050, "Varalakshmi Vratam", 1.05, 0))

    def test_pune_regional_festival_is_supported(self):
        features = main._festival_features("PNQ", pd.Timestamp("2026-02-19"))
        self.assertEqual(features["is_city_festival"], 1)

    def test_parsi_new_year_is_scoped_to_pune(self):
        target = pd.Timestamp("2026-08-15")
        self.assertEqual(main._festival_features("PNQ", target)["is_city_festival"], 1)
        self.assertEqual(main._festival_features("BLR", target)["is_city_festival"], 0)

    def test_operational_frame_keeps_only_each_citys_due_target(self):
        rows = []
        for forecast_date in ("2026-08-09", "2026-08-10"):
            for city in main.FORECAST_LEAD_DAYS:
                rows.append({
                    "forecast_date": forecast_date,
                    "city_cd": city,
                    "product_name": "Cow Milk",
                    "method": "subscription",
                    "predicted_qty": 100,
                })
        frame = main._forecast_rows_to_operational_df(rows, pd.Timestamp("2026-08-07"))
        actual = set(zip(frame["city"], frame["forecast_date"]))
        self.assertEqual(actual, {
            ("HYD", "2026-08-09"),
            ("VGA", "2026-08-09"),
            ("BLR", "2026-08-10"),
            ("PNQ", "2026-08-10"),
        })

    def test_target_frame_returns_one_selected_date_for_every_city(self):
        rows = [
            {
                "forecast_date": "2026-08-08",
                "city_cd": city,
                "product_name": "Cow Milk",
                "method": "subscription",
                "predicted_qty": 100,
            }
            for city in main.FORECAST_LEAD_DAYS
        ]
        frame = main._forecast_rows_to_operational_df(
            rows, target_date=pd.Timestamp("2026-08-08")
        )
        self.assertEqual(set(frame["forecast_date"]), {"2026-08-08"})
        self.assertEqual(set(frame["city"]), set(main.FORECAST_LEAD_DAYS))
        issue_dates = dict(zip(frame["city"], frame["issue_date"]))
        self.assertEqual(issue_dates["HYD"], "2026-08-06")
        self.assertEqual(issue_dates["BLR"], "2026-08-05")
        self.assertTrue(
            frame["remaining_model_gap_qty"].eq(
                frame["ml_unknown_adhoc_qty"]
            ).all()
        )

    def test_issuance_recent_actuals_exclude_dates_after_issue_date(self):
        subscription = pd.DataFrame([
            {"city_cd": city, "product_name": "Cow Milk", "daily_qty": 10}
            for city in ("HYD", "VGA")
        ])
        known = pd.DataFrame([
            {"city_cd": "HYD", "product_name": "Cow Milk", "daily_qty": 2}
        ])
        recent = pd.DataFrame([
            {
                "target_date": date,
                "city_cd": city,
                "product_name": "Cow Milk",
                "total_qty": 100,
            }
            for date in ("2026-08-17", "2026-08-18", "2026-08-19")
            for city in ("HYD", "VGA")
        ])
        result = main._validate_issuance_inputs(
            target_date="2026-08-20",
            issue_date=pd.Timestamp("2026-08-18"),
            relevant_cities={"HYD", "VGA"},
            subscription_df=subscription,
            known_df=known,
            recent_df=recent,
        )
        self.assertEqual(
            pd.Timestamp(result["target_date"].max()), pd.Timestamp("2026-08-17")
        )


class AtomicIssuanceCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_issuance_restores_the_last_good_redash_cache(self):
        cache_at_test_start = dict(main._redash_cache)
        original = {("subscription", 3085, "old"): {"df": "old", "fetched_at": 1}}
        main._redash_cache.clear()
        main._redash_cache.update(original)

        async def fail_after_partial_update(*args, **kwargs):
            main._redash_cache[("subscription", 3085, "new")] = {
                "df": "partial", "fetched_at": 2,
            }
            raise RuntimeError("query failed")

        try:
            with patch.object(
                main,
                "_issue_daily_operational_forecast_once",
                new=AsyncMock(side_effect=fail_after_partial_update),
            ):
                with self.assertRaises(RuntimeError):
                    await main.issue_daily_operational_forecast("2026-08-18")
            self.assertEqual(main._redash_cache, original)
        finally:
            main._redash_cache.clear()
            main._redash_cache.update(cache_at_test_start)


if __name__ == "__main__":
    unittest.main()
