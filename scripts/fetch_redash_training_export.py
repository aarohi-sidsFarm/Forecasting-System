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
    parser.add_argument(
        "--append",
        action="store_true",
        help="Merge the fetched window into the existing CSV by date/city/product.",
    )
    parser.add_argument(
        "--maximum-overlap-wape",
        type=float,
        default=30.0,
        help="Reject the merge when changed overlapping totals exceed this WAPE.",
    )
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
        for _ in range(200):
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
    raise TimeoutError("Redash training export did not finish within 10 minutes.")


def _row_key(row: dict) -> tuple[str, str, str]:
    return (
        str(row["target_date"]),
        str(row["city_cd"]),
        str(row["product_name"]),
    )


def _read_existing(output: Path) -> list[dict]:
    if not output.exists():
        return []
    with output.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(
    rows: list[dict],
    output: Path,
    *,
    append: bool = False,
    maximum_overlap_wape: float = 30.0,
) -> None:
    if not rows:
        raise RuntimeError("Redash returned zero rows; not overwriting training CSV.")
    missing = REQUIRED_COLUMNS.difference(rows[0].keys())
    if missing:
        raise RuntimeError(f"Training export missing required columns: {sorted(missing)}")

    existing = _read_existing(output) if append else []
    if existing:
        existing_missing = REQUIRED_COLUMNS.difference(existing[0].keys())
        if existing_missing:
            raise RuntimeError(
                f"Existing training export is missing columns: {sorted(existing_missing)}"
            )
        existing_by_key = {_row_key(row): row for row in existing}
        incoming_by_key = {_row_key(row): row for row in rows}
        overlap_keys = existing_by_key.keys() & incoming_by_key.keys()
        if overlap_keys:
            absolute_change = sum(
                abs(
                    float(incoming_by_key[key]["final_total_qty"] or 0)
                    - float(existing_by_key[key]["final_total_qty"] or 0)
                )
                for key in overlap_keys
            )
            existing_total = sum(
                abs(float(existing_by_key[key]["final_total_qty"] or 0))
                for key in overlap_keys
            )
            overlap_wape = 100 * absolute_change / existing_total if existing_total else 0.0
            print(
                f"Overlap audit: {len(overlap_keys)} keys, "
                f"historical-change WAPE {overlap_wape:.2f}%"
            )
            if overlap_wape > maximum_overlap_wape:
                raise RuntimeError(
                    f"Historical overlap changed by {overlap_wape:.2f}% "
                    f"(limit {maximum_overlap_wape:.2f}%); export not overwritten"
                )
        existing_by_key.update(incoming_by_key)
        rows = [existing_by_key[key] for key in sorted(existing_by_key)]

    output.parent.mkdir(parents=True, exist_ok=True)
    columns = list(rows[0].keys())
    temporary = output.with_suffix(output.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(output)


def main() -> None:
    load_env_file(ROOT / ".env")
    load_env_file(ROOT / "backend" / ".env")
    args = arguments()
    rows = asyncio.run(fetch_rows(args.query_id, args.start_date, args.end_date, args.max_age))
    output = Path(args.output)
    write_csv(
        rows,
        output,
        append=args.append,
        maximum_overlap_wape=args.maximum_overlap_wape,
    )
    print(f"Saved {len(rows)} rows to {output}")
    print(f"Date window: {args.start_date} -> {args.end_date}")


if __name__ == "__main__":
    main()
