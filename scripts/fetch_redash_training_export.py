"""Download the procurement final-total training export from Redash.

This keeps model retraining repeatable: fetch latest Redash data, save it to
the exact CSV path consumed by ml_pipeline/process_all_data.py, then run the
normal training commands.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
from datetime import date, timedelta
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "raw" / "redash_exports" / "procurement_final_total_training.csv"
REQUIRED_COLUMNS = {
    "target_date",
    "city_cd",
    "product_name",
    "final_subscription_qty",
    "final_buy_once_qty",
    "final_total_qty",
    "final_orders",
}


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def arguments() -> argparse.Namespace:
    yesterday = date.today() - timedelta(days=1)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--query-id",
        type=int,
        default=int(os.getenv("PROCUREMENT_TRAINING_QUERY_ID", "0") or 0),
        help="Redash query ID for redash_queries/procurement_final_total_training.sql.",
    )
    parser.add_argument("--start-date", default="2025-05-01")
    parser.add_argument("--end-date", default=yesterday.isoformat())
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--max-age", type=int, default=0)
    return parser.parse_args()


async def fetch_rows(query_id: int, start_date: str, end_date: str, max_age: int) -> list[dict]:
    base_url = os.environ.get("REDASH_BASE_URL", "https://analytics.sidsfarm.in").rstrip("/")
    api_key = os.environ.get("QUERY_API_KEY")
    if not api_key:
        raise RuntimeError("QUERY_API_KEY is missing. Add it to backend/.env or the shell environment.")
    if not query_id:
        raise RuntimeError("Missing --query-id or PROCUREMENT_TRAINING_QUERY_ID.")

    headers = {"Authorization": f"Key {api_key}", "Content-Type": "application/json"}
    payload = {
        "parameters": {"start_date": start_date, "end_date": end_date},
        "max_age": max_age,
    }
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            f"{base_url}/api/queries/{query_id}/results",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
        rows = body.get("query_result", {}).get("data", {}).get("rows")
        if rows is not None:
            return rows

        job_id = body.get("job", {}).get("id")
        if not job_id:
            raise RuntimeError(f"Unexpected Redash response: {body}")
        for _ in range(60):
            await asyncio.sleep(3)
            job_response = await client.get(f"{base_url}/api/jobs/{job_id}", headers=headers)
            job_response.raise_for_status()
            job = job_response.json()["job"]
            if job["status"] == 3:
                result_response = await client.get(
                    f"{base_url}/api/query_results/{job['query_result_id']}",
                    headers=headers,
                )
                result_response.raise_for_status()
                return result_response.json()["query_result"]["data"]["rows"]
            if job["status"] == 4:
                raise RuntimeError(f"Redash job failed: {job}")
    raise TimeoutError("Redash training export did not finish within 3 minutes.")


def write_csv(rows: list[dict], output: Path) -> None:
    if not rows:
        raise RuntimeError("Redash returned zero rows; not overwriting training CSV.")
    missing = REQUIRED_COLUMNS.difference(rows[0].keys())
    if missing:
        raise RuntimeError(f"Training export missing required columns: {sorted(missing)}")

    output.parent.mkdir(parents=True, exist_ok=True)
    columns = list(rows[0].keys())
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    load_env_file(ROOT / ".env")
    load_env_file(ROOT / "backend" / ".env")
    args = arguments()
    rows = asyncio.run(fetch_rows(args.query_id, args.start_date, args.end_date, args.max_age))
    output = Path(args.output)
    write_csv(rows, output)
    print(f"Saved {len(rows)} rows to {output}")
    print(f"Date window: {args.start_date} -> {args.end_date}")


if __name__ == "__main__":
    main()
