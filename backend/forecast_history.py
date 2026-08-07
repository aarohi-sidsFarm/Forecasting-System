"""Immutable forecast-run history for audit and shadow evaluation."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

IST = ZoneInfo("Asia/Kolkata")


def default_db_path() -> str:
    return os.getenv(
        "FORECAST_HISTORY_DB",
        os.path.join(os.path.dirname(__file__), "ml_models", "forecast_history.db"),
    )


def connect(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or default_db_path()
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def db_connection(db_path: str | None = None):
    connection = connect(db_path)
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize(db_path: str | None = None) -> None:
    with db_connection(db_path) as connection:
        connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS forecast_runs (
                run_id TEXT PRIMARY KEY,
                generated_at TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                run_kind TEXT NOT NULL,
                model_version TEXT,
                cutoff_policy TEXT,
                metadata_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS forecast_rows (
                run_id TEXT NOT NULL,
                forecast_date TEXT NOT NULL,
                horizon INTEGER NOT NULL,
                city_cd TEXT NOT NULL,
                product_name TEXT NOT NULL,
                p50_qty REAL NOT NULL,
                p80_qty REAL,
                method TEXT,
                visible_subscription_qty REAL,
                visible_buy_once_qty REAL,
                visible_orders REAL,
                PRIMARY KEY (run_id, forecast_date, city_cd, product_name)
            );
            CREATE INDEX IF NOT EXISTS idx_forecast_rows_lookup
                ON forecast_rows(forecast_date, city_cd, product_name);
            CREATE TABLE IF NOT EXISTS final_actual_rows (
                forecast_date TEXT NOT NULL,
                city_cd TEXT NOT NULL,
                product_name TEXT NOT NULL,
                actual_qty REAL NOT NULL,
                actual_loaded_at TEXT NOT NULL,
                PRIMARY KEY (forecast_date, city_cd, product_name)
            );
            """
        )
        existing_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(forecast_rows)")
        }
        for column in [
            "visible_subscription_qty", "visible_buy_once_qty", "visible_orders"
        ]:
            if column not in existing_columns:
                connection.execute(
                    f"ALTER TABLE forecast_rows ADD COLUMN {column} REAL"
                )


def record_run(
    rows: pd.DataFrame,
    *,
    run_kind: str,
    model_version: str,
    cutoff_policy: str,
    metadata: dict | None = None,
    generated_at: str | None = None,
    db_path: str | None = None,
) -> dict:
    required = {"forecast_date", "city_cd", "product_name", "p50_qty"}
    if missing := required.difference(rows.columns):
        raise ValueError(f"Forecast history rows missing: {sorted(missing)}")
    frame = rows.copy()
    frame["forecast_date"] = pd.to_datetime(frame.forecast_date).dt.strftime("%Y-%m-%d")
    frame["city_cd"] = frame.city_cd.astype(str).str.upper().str.strip()
    frame["product_name"] = frame.product_name.astype(str).str.strip()
    frame["p50_qty"] = pd.to_numeric(frame.p50_qty, errors="raise")
    if "p80_qty" not in frame:
        frame["p80_qty"] = None
    if "method" not in frame:
        frame["method"] = None
    for column in [
        "visible_subscription_qty", "visible_buy_once_qty", "visible_orders"
    ]:
        if column not in frame:
            frame[column] = None
    start = pd.Timestamp(frame.forecast_date.min())
    frame["horizon"] = (pd.to_datetime(frame.forecast_date) - start).dt.days + 1
    timestamp = generated_at or datetime.now(IST).isoformat()
    run_id = str(uuid.uuid4())
    initialize(db_path)
    with db_connection(db_path) as connection:
        connection.execute(
            """
            INSERT INTO forecast_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, timestamp, str(start.date()), frame.forecast_date.max(),
                run_kind, model_version, cutoff_policy,
                json.dumps(metadata or {}, sort_keys=True),
            ),
        )
        connection.executemany(
            """
            INSERT INTO forecast_rows
            (run_id, forecast_date, horizon, city_cd, product_name,
             p50_qty, p80_qty, method, visible_subscription_qty,
             visible_buy_once_qty, visible_orders)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id, row.forecast_date, int(row.horizon), row.city_cd,
                    row.product_name, float(row.p50_qty),
                    None if pd.isna(row.p80_qty) else float(row.p80_qty), row.method,
                    None if pd.isna(row.visible_subscription_qty) else float(row.visible_subscription_qty),
                    None if pd.isna(row.visible_buy_once_qty) else float(row.visible_buy_once_qty),
                    None if pd.isna(row.visible_orders) else float(row.visible_orders),
                )
                for row in frame.itertuples(index=False)
            ],
        )
    return {
        "run_id": run_id,
        "generated_at": timestamp,
        "start_date": str(start.date()),
        "end_date": frame.forecast_date.max(),
        "rows": len(frame),
    }


def upsert_actuals(actuals: pd.DataFrame, db_path: str | None = None) -> int:
    required = {"forecast_date", "city_cd", "product_name", "actual_qty"}
    if missing := required.difference(actuals.columns):
        raise ValueError(f"Actual rows missing: {sorted(missing)}")
    frame = actuals.copy()
    frame["forecast_date"] = pd.to_datetime(frame.forecast_date).dt.strftime("%Y-%m-%d")
    loaded_at = datetime.now(IST).isoformat()
    initialize(db_path)
    with db_connection(db_path) as connection:
        connection.executemany(
            """
            INSERT INTO final_actual_rows VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(forecast_date, city_cd, product_name)
            DO UPDATE SET actual_qty=excluded.actual_qty,
                          actual_loaded_at=excluded.actual_loaded_at
            """,
            [
                (
                    row.forecast_date, str(row.city_cd).upper().strip(),
                    str(row.product_name).strip(), float(row.actual_qty), loaded_at,
                )
                for row in frame.itertuples(index=False)
            ],
        )
    return len(frame)


def issued_forecast_for_date(
    forecast_date: str, db_path: str | None = None
) -> tuple[pd.DataFrame, dict | None]:
    """Return the latest officially issued forecast covering a target date."""
    normalized = pd.Timestamp(forecast_date).strftime("%Y-%m-%d")
    initialize(db_path)
    with db_connection(db_path) as connection:
        run = connection.execute(
            """
            SELECT run_id, generated_at, run_kind, model_version, metadata_json
            FROM forecast_runs
            WHERE run_kind IN ('official_export', 'official_import')
              AND start_date <= ? AND end_date >= ?
            ORDER BY generated_at DESC
            LIMIT 1
            """,
            (normalized, normalized),
        ).fetchone()
        if run is None:
            return pd.DataFrame(), None
        rows = pd.read_sql_query(
            """
            SELECT forecast_date, city_cd, product_name, p50_qty,
                   p80_qty, method, visible_subscription_qty,
                   visible_buy_once_qty, visible_orders
            FROM forecast_rows
            WHERE run_id=? AND forecast_date=?
            """,
            connection,
            params=(run["run_id"], normalized),
        )
        info = dict(run)
        info["metadata"] = json.loads(info.pop("metadata_json") or "{}")
        return rows, info


initialize()
