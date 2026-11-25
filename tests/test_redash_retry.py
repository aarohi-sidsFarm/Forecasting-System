import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import pandas as pd

from backend import main

REPLICA_ERROR = RuntimeError(
    "Required Redash input subscription failed for 2026-11-26: Redash job failed: "
    "error=canceling statement due to conflict with recovery"
)


def _run(**kwargs):
    return asyncio.run(main._fetch_redash_rows(3085, "2026-11-26", "subscription", **kwargs))


@patch.object(main, "REDASH_TRANSIENT_RETRY_DELAY_SECONDS", 0)
class RedashRetryTests(unittest.TestCase):
    def test_issuance_reruns_the_query_after_a_replica_error(self):
        rows = pd.DataFrame([{"city_cd": "HYD"}])
        once = AsyncMock(side_effect=[REPLICA_ERROR, rows])
        with patch.object(main, "_fetch_redash_rows_once", once):
            result = _run(strict=True, wait_mode="issuance")
        self.assertIs(result, rows)
        self.assertEqual(once.await_count, 2)
        # The retry must skip the 60-second failure cooldown.
        self.assertTrue(once.await_args_list[1].kwargs["force_refresh"])

    def test_gives_up_after_the_retry_limit(self):
        once = AsyncMock(side_effect=REPLICA_ERROR)
        with patch.object(main, "_fetch_redash_rows_once", once):
            with self.assertRaises(RuntimeError):
                _run(strict=True, wait_mode="issuance")
        self.assertEqual(once.await_count, 1 + main.REDASH_TRANSIENT_RETRIES)

    def test_other_errors_are_not_retried(self):
        once = AsyncMock(side_effect=RuntimeError("Redash subscription returned no rows"))
        with patch.object(main, "_fetch_redash_rows_once", once):
            with self.assertRaises(RuntimeError):
                _run(strict=True, wait_mode="issuance")
        self.assertEqual(once.await_count, 1)

    def test_dashboard_reads_do_not_retry(self):
        once = AsyncMock(side_effect=REPLICA_ERROR)
        with patch.object(main, "_fetch_redash_rows_once", once):
            with self.assertRaises(RuntimeError):
                _run(strict=True, wait_mode="interactive")
        self.assertEqual(once.await_count, 1)


if __name__ == "__main__":
    unittest.main()
