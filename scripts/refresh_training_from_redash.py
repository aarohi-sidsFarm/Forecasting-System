"""Refresh final-actual training data while excluding approximate snapshots."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

import httpx
import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/raw/redash_exports/procurement_final_total_training.csv"


async def run_query(query_id: int, start: str, end: str) -> pd.DataFrame:
    load_dotenv(ROOT / ".env")
    base = os.environ["REDASH_BASE_URL"].rstrip("/")
    headers = {
        "Authorization": f"Key {os.environ['QUERY_API_KEY']}",
        "Content-Type": "application/json",
    }
    payload = {"parameters": {"start_date": start, "end_date": end}, "max_age": 0}
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{base}/api/queries/{query_id}/results", headers=headers, json=payload
        )
        response.raise_for_status()
        result = response.json()
        rows = result.get("query_result", {}).get("data", {}).get("rows")
        if rows is None:
            for _ in range(80):
                await asyncio.sleep(3)
                job_response = await client.get(
                    f"{base}/api/jobs/{result['job']['id']}", headers=headers
                )
                job_response.raise_for_status()
                job = job_response.json()["job"]
                if job["status"] == 3:
                    data_response = await client.get(
                        f"{base}/api/query_results/{job['query_result_id']}",
                        headers=headers,
                    )
                    data_response.raise_for_status()
                    rows = data_response.json()["query_result"]["data"]["rows"]
                    break
                if job["status"] == 4:
                    raise RuntimeError(f"Redash job failed: {job}")
    if rows is None:
        raise TimeoutError("Redash training refresh timed out")
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query-id", type=int, default=3084)
    parser.add_argument("--start", default="2025-05-01")
    parser.add_argument(
        "--end",
        default=str(
            (pd.Timestamp.now(tz="Asia/Kolkata").normalize() - pd.Timedelta(days=1)).date()
        ),
    )
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args()

    raw = asyncio.run(run_query(args.query_id, args.start, args.end))
    required = [
        "target_date", "city_cd", "product_name", "final_subscription_qty",
        "final_buy_once_qty", "final_total_qty", "final_orders",
    ]
    if missing := set(required).difference(raw.columns):
        raise ValueError(f"Training result missing columns: {sorted(missing)}")
    clean = raw[required].copy()
    clean["target_date"] = pd.to_datetime(clean.target_date).dt.strftime("%Y-%m-%d")
    clean["snapshot_is_exact"] = False
    clean = clean.sort_values(["target_date", "city_cd", "product_name"])
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    clean.to_csv(temporary, index=False)
    temporary.replace(output)
    print(
        f"Saved {len(clean)} rows to {output}; "
        f"{clean.target_date.min()} -> {clean.target_date.max()}"
    )


if __name__ == "__main__":
    main()
