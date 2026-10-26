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
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


_initialized_paths: set[str] = set()


def initialize(db_path: str | None = None) -> None:
    # Schema setup is idempotent but not free; every API request used to
    # re-run it. Do it once per database file per process.
    path = os.path.abspath(db_path or default_db_path())
    if path in _initialized_paths and os.path.exists(path):
        return
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
                metadata_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'complete'
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
                issue_date TEXT,
                confirmed_subscription_qty REAL,
                at_risk_subscription_qty REAL,
                ml_unknown_adhoc_qty REAL,
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
            "visible_subscription_qty", "visible_buy_once_qty", "visible_orders",
            "issue_date", "confirmed_subscription_qty",
            "at_risk_subscription_qty", "ml_unknown_adhoc_qty",
        ]:
            if column not in existing_columns:
                column_type = "TEXT" if column == "issue_date" else "REAL"
                connection.execute(
                    f"ALTER TABLE forecast_rows ADD COLUMN {column} {column_type}"
                )
        run_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(forecast_runs)")
        }
        if "status" not in run_columns:
            connection.execute(
                "ALTER TABLE forecast_runs ADD COLUMN status TEXT NOT NULL DEFAULT 'complete'"
            )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_issued_forecast_key
            ON forecast_rows(issue_date, forecast_date, city_cd, product_name)
            WHERE issue_date IS NOT NULL
            """
        )
    _initialized_paths.add(path)


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
    if rows.empty:
        raise ValueError("Forecast history run cannot be empty")
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
        "visible_subscription_qty", "visible_buy_once_qty", "visible_orders",
        "confirmed_subscription_qty", "at_risk_subscription_qty",
        "ml_unknown_adhoc_qty",
    ]:
        if column not in frame:
            frame[column] = None
    if "issue_date" not in frame:
        frame["issue_date"] = None
    frame["issue_date"] = frame["issue_date"].apply(
        lambda value: None if pd.isna(value) else pd.Timestamp(value).strftime("%Y-%m-%d")
    )
    if run_kind == "official_issued" and frame["issue_date"].isna().any():
        raise ValueError("official_issued rows require issue_date")
    start = pd.Timestamp(frame.forecast_date.min())
    if "horizon" in frame:
        frame["horizon"] = pd.to_numeric(frame["horizon"], errors="raise").astype(int)
    else:
        frame["horizon"] = (pd.to_datetime(frame.forecast_date) - start).dt.days + 1
    timestamp = generated_at or datetime.now(IST).isoformat()
    run_id = str(uuid.uuid4())
    initialize(db_path)
    with db_connection(db_path) as connection:
        connection.execute(
            """
            INSERT INTO forecast_runs
            (run_id, generated_at, start_date, end_date, run_kind,
             model_version, cutoff_policy, metadata_json, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, timestamp, str(start.date()), frame.forecast_date.max(),
                run_kind, model_version, cutoff_policy,
                json.dumps(metadata or {}, sort_keys=True), "complete",
            ),
        )
        connection.executemany(
            """
            INSERT INTO forecast_rows
            (run_id, forecast_date, horizon, city_cd, product_name,
             p50_qty, p80_qty, method, visible_subscription_qty,
             visible_buy_once_qty, visible_orders, issue_date,
             confirmed_subscription_qty, at_risk_subscription_qty,
             ml_unknown_adhoc_qty)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id, row.forecast_date, int(row.horizon), row.city_cd,
                    row.product_name, float(row.p50_qty),
                    None if pd.isna(row.p80_qty) else float(row.p80_qty), row.method,
                    None if pd.isna(row.visible_subscription_qty) else float(row.visible_subscription_qty),
                    None if pd.isna(row.visible_buy_once_qty) else float(row.visible_buy_once_qty),
                    None if pd.isna(row.visible_orders) else float(row.visible_orders),
                    row.issue_date,
                    None if pd.isna(row.confirmed_subscription_qty) else float(row.confirmed_subscription_qty),
                    None if pd.isna(row.at_risk_subscription_qty) else float(row.at_risk_subscription_qty),
                    None if pd.isna(row.ml_unknown_adhoc_qty) else float(row.ml_unknown_adhoc_qty),
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
    forecast_date: str,
    db_path: str | None = None,
    *,
    include_exports: bool = True,
) -> tuple[pd.DataFrame, dict | None]:
    """Return the best immutable issued rows for every city/SKU on a target date.

    official_export runs are CSV downloads, not cutoff-time issuances; pass
    include_exports=False wherever rows are presented as the issued forecast.
    """
    normalized = pd.Timestamp(forecast_date).strftime("%Y-%m-%d")
    run_kinds = ["official_issued", "official_import"]
    if include_exports:
        run_kinds.append("official_export")
    initialize(db_path)
    with db_connection(db_path) as connection:
        placeholders = ", ".join("?" for _ in run_kinds)
        rows = pd.read_sql_query(
            f"""
            WITH ranked AS (
                SELECT fr.*, r.generated_at, r.run_kind, r.model_version,
                       r.metadata_json,
                       ROW_NUMBER() OVER (
                           PARTITION BY fr.city_cd, fr.product_name
                           ORDER BY
                               CASE r.run_kind
                                   WHEN 'official_issued' THEN 0
                                   WHEN 'official_import' THEN 1
                                   ELSE 2
                               END,
                               r.generated_at DESC
                       ) AS row_rank
                FROM forecast_rows fr
                JOIN forecast_runs r ON r.run_id=fr.run_id
                WHERE r.run_kind IN ({placeholders})
                  AND r.status='complete'
                  AND fr.forecast_date=?
            )
            SELECT run_id, forecast_date, horizon, city_cd, product_name,
                   p50_qty, p80_qty, method, visible_subscription_qty,
                   visible_buy_once_qty, visible_orders, issue_date,
                   confirmed_subscription_qty, at_risk_subscription_qty,
                   ml_unknown_adhoc_qty, generated_at, run_kind,
                   model_version, metadata_json
            FROM ranked
            WHERE row_rank=1
            """,
            connection,
            params=(*run_kinds, normalized),
        )
        if rows.empty:
            return pd.DataFrame(), None
        run_info = []
        for run_id, group in rows.groupby("run_id", sort=False):
            first = group.iloc[0]
            run_info.append({
                "run_id": run_id,
                "generated_at": first["generated_at"],
                "run_kind": first["run_kind"],
                "model_version": first["model_version"],
                "metadata": json.loads(first["metadata_json"] or "{}"),
            })
        info = {
            "run_id": run_info[0]["run_id"] if len(run_info) == 1 else None,
            "run_ids": [item["run_id"] for item in run_info],
            "generated_at": max(item["generated_at"] for item in run_info),
            "run_kind": "official_issued"
            if all(item["run_kind"] == "official_issued" for item in run_info)
            else "mixed_issued_history",
            "runs": run_info,
        }
        return rows.drop(
            columns=["generated_at", "run_kind", "model_version", "metadata_json"]
        ), info


def issued_run_for_issue_date(
    issue_date: str, db_path: str | None = None
) -> dict | None:
    """Return an existing successful daily issuance, if one exists."""
    normalized = pd.Timestamp(issue_date).strftime("%Y-%m-%d")
    initialize(db_path)
    with db_connection(db_path) as connection:
        row = connection.execute(
            """
            SELECT r.run_id, r.generated_at, r.start_date, r.end_date,
                   r.model_version, r.metadata_json, COUNT(fr.product_name) AS rows
            FROM forecast_runs r
            JOIN forecast_rows fr ON fr.run_id=r.run_id
            WHERE r.run_kind='official_issued'
              AND r.status='complete'
              AND fr.issue_date=?
            GROUP BY r.run_id
            ORDER BY r.generated_at DESC
            LIMIT 1
            """,
            (normalized,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
        return result


initialize()
