"""Spark-side helpers shared by train.py and score.py."""
from __future__ import annotations

import os
import sys

import pandas as pd

MODEL_BASENAME = "aftersales_demand_forecaster"


def bootstrap_path() -> None:
    """Make `aftersales` importable when the task file runs from the synced bundle (src/ is two levels up)."""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        here = os.getcwd()
    sys.path.insert(0, os.path.dirname(os.path.dirname(here)))


def get_spark():
    from pyspark.sql import SparkSession
    return SparkSession.builder.getOrCreate()


def read(spark, prefix: str, table: str) -> pd.DataFrame:
    return spark.table(f"{prefix}.{table}").toPandas()


def load_inputs(spark, prefix: str) -> dict[str, pd.DataFrame]:
    demand = read(spark, prefix, "aftersales_demand_weekly")
    demand["week_start"] = pd.to_datetime(demand["week_start"])
    for c in ("demand_units", "sold_units", "active_fleet_units"):
        demand[c] = demand[c].astype(float)
    parts, dealers = read(spark, prefix, "aftersales_parts"), read(spark, prefix, "aftersales_dealers")
    parts["is_critical"] = parts["is_critical"].astype(bool)
    stock = read(spark, prefix, "aftersales_stock_position")
    return {"demand": demand, "parts": parts, "dealers": dealers, "stock": stock}
