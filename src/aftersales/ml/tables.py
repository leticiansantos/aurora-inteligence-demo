"""ML output tables: DDL + pandas -> Spark record conversion. Mirrors docs/data-model/aftersales.md (frozen v1)."""
from __future__ import annotations

import datetime as dt
import math

import pandas as pd

# name -> (table comment, [(column, type, comment)])
TABLES: dict[str, tuple[str, list[tuple[str, str, str]]]] = {
    "aftersales_forecast_weekly": (
        "Synthetic aftersales weekly demand: 26 history weeks, 13-week backtest and 8 future weeks per dealer x part (written by job aftersales_daily, task score).",
        [("dealer_id", "STRING", "Synthetic dealer id (D001..D012)"),
         ("part_id", "STRING", "Synthetic part id (P001..P060)"),
         ("week_start", "DATE", "Monday of the week"),
         ("is_future", "BOOLEAN", "True for forecast weeks after the last actual week"),
         ("horizon_week", "INT", "Weeks ahead from the forecast origin (backtest 1..13 from the cutoff, future 1..8); null for pure history"),
         ("actual_units", "DOUBLE", "Synthetic demand in units (null for future weeks)"),
         ("sold_units", "DOUBLE", "Synthetic units actually sold (null for future weeks)"),
         ("forecast_units", "DOUBLE", "Model forecast in units (backtest and future rows only)"),
         ("lower_units", "DOUBLE", "80% interval lower bound, floored at 0"),
         ("upper_units", "DOUBLE", "80% interval upper bound"),
         ("baseline_units", "DOUBLE", "Seasonal-naive (52 weeks) forecast; backtest rows only"),
         ("forecast_date", "DATE", "First forecast week (the scoring origin + 1 week)"),
         ("model_version", "STRING", "Unity Catalog model version of the champion that produced the forecast"),
         ("scored_at", "TIMESTAMP", "When the score task ran")]),
    "aftersales_model_metrics": (
        "Synthetic aftersales forecast model registry log: backtest WAPE of each trained model version vs the seasonal-naive baseline.",
        [("model_name", "STRING", "Unity Catalog model name"),
         ("model_version", "STRING", "Model version (primary key)"),
         ("run_id", "STRING", "MLflow run id of the training run"),
         ("cutoff_date", "DATE", "Last day of the training window of the backtest"),
         ("forecast_date", "DATE", "First forecast week of the final model"),
         ("holdout_weeks", "INT", "Number of holdout weeks"),
         ("n_series", "INT", "Number of dealer x part series"),
         ("wape", "DOUBLE", "Backtest WAPE of the model: sum|y-yhat| / sum y"),
         ("baseline_wape", "DOUBLE", "Backtest WAPE of the seasonal-naive baseline"),
         ("bias", "DOUBLE", "Backtest bias of the model: sum(yhat-y) / sum y"),
         ("baseline_bias", "DOUBLE", "Backtest bias of the baseline"),
         ("is_champion", "BOOLEAN", "True if this version holds the champion alias"),
         ("logged_at", "TIMESTAMP", "When the metrics were logged")]),
    "aftersales_stockout_risk": (
        "Synthetic aftersales stockout risk and replenishment recommendation per dealer x part x horizon (written by job aftersales_daily, task score).",
        [("dealer_id", "STRING", "Synthetic dealer id"),
         ("part_id", "STRING", "Synthetic part id"),
         ("horizon_days", "INT", "Horizon in days: 14, 28 or 56"),
         ("forecast_date", "DATE", "First forecast week"),
         ("stock_units", "INT", "On-hand units"),
         ("on_order_units", "INT", "Units on order (treated as guaranteed)"),
         ("available_units", "INT", "On hand + on order"),
         ("lead_time_days", "INT", "Supplier lead time in days"),
         ("forecast_units", "DOUBLE", "Forecast demand over the horizon"),
         ("forecast_sigma_units", "DOUBLE", "Forecast standard deviation over the horizon: sigma*sqrt(H)"),
         ("safety_stock_units", "DOUBLE", "1.65 * sigma * sqrt(lead_time/7)"),
         ("days_of_stock", "DOUBLE", "On-hand units / forecast daily demand; null when the forecast is zero"),
         ("days_to_stockout", "INT", "First day (1..56) when cumulative forecast demand exceeds available units; null if none"),
         ("stockout_probability", "DOUBLE", "1 - Phi((available - mu)/(sigma*sqrt(H)))"),
         ("risk_level", "STRING", "critical | high | medium | low"),
         ("shortfall_units", "INT", "ceil(max(0, mu + safety stock - available))"),
         ("lost_sales_brl", "DOUBLE", "Revenue lost if nothing is done: max(0, mu - available) * unit price"),
         ("action", "STRING", "reorder | transfer | monitor"),
         ("recommended_qty", "INT", "Units to reorder or transfer"),
         ("transfer_from_dealer_id", "STRING", "Donor dealer when action = transfer"),
         ("transfer_from_excess_units", "INT", "Donor remaining excess before this allocation"),
         ("model_version", "STRING", "Champion model version used"),
         ("scored_at", "TIMESTAMP", "When the score task ran")]),
}

PK = {
    "aftersales_forecast_weekly": ["dealer_id", "part_id", "week_start"],
    "aftersales_model_metrics": ["model_version"],
    "aftersales_stockout_risk": ["dealer_id", "part_id", "horizon_days"],
}


def ddl_columns(table: str) -> str:
    return ", ".join(f"{c} {t}" for c, t, _ in TABLES[table][1])


def column_names(table: str) -> list[str]:
    return [c for c, _, _ in TABLES[table][1]]


def ensure_table(spark, fq_prefix: str, table: str) -> str:
    """Create the table with the contract schema and comments if missing; return its full name."""
    fq = f"{fq_prefix}.{table}"
    comment, cols = TABLES[table]
    col_sql = ", ".join(f"{c} {t} COMMENT '{d}'" for c, t, d in cols)
    spark.sql(f"CREATE TABLE IF NOT EXISTS {fq} ({col_sql}) COMMENT '{comment}'")
    return fq


def _py(value, typ: str):
    if value is None or (isinstance(value, float) and math.isnan(value)) or value is pd.NaT:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if typ == "DATE":
        return pd.Timestamp(value).date() if not isinstance(value, dt.date) or isinstance(value, dt.datetime) else value
    if typ == "TIMESTAMP":
        return pd.Timestamp(value).to_pydatetime()
    if typ == "INT":
        return int(value)
    if typ == "DOUBLE":
        return float(value)
    if typ == "BOOLEAN":
        return bool(value)
    return str(value)


def to_records(df: pd.DataFrame, table: str) -> list[tuple]:
    """Rows in contract column order with python types matching the DDL (NaN -> None)."""
    cols = TABLES[table][1]
    missing = [c for c, _, _ in cols if c not in df]
    if missing:
        raise ValueError(f"{table}: missing columns {missing}")
    return [tuple(_py(v, t) for v, (_, t, _) in zip(row, cols))
            for row in df[[c for c, _, _ in cols]].itertuples(index=False, name=None)]


def overwrite(spark, fq: str, table: str, df: pd.DataFrame) -> int:
    """Idempotent full overwrite keeping table properties/tags (INSERT OVERWRITE semantics)."""
    existing = list(spark.table(fq).columns)
    if existing != column_names(table):
        raise RuntimeError(f"{fq} columns {existing} differ from the contract {column_names(table)}")
    sdf = spark.createDataFrame(to_records(df, table), schema=ddl_columns(table))
    sdf.write.mode("overwrite").insertInto(fq)
    return len(df)
