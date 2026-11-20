"""Pure assembly of the ML output tables (no Spark, no MLflow) so it is unit-testable."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .forecast import KEYS, PERIOD

Z80 = 1.2816
HISTORY_WEEKS = 26
SIGMA_FLOOR = 0.5


def series_sigma(backtest_pred: pd.DataFrame) -> pd.DataFrame:
    """sigma per series = max(RMSE of the holdout, 0.5)."""
    g = backtest_pred.assign(se=(backtest_pred.actual - backtest_pred.forecast) ** 2).groupby(KEYS)["se"].mean()
    return (np.sqrt(g).clip(lower=SIGMA_FLOOR)).rename("sigma").reset_index()


def build_forecast_weekly(demand: pd.DataFrame, backtest_pred: pd.DataFrame, future_pred: pd.DataFrame,
                          sigma: pd.DataFrame, *, model_version: str, scored_at) -> pd.DataFrame:
    """26 history weeks (13 of them backtested) + 8 future weeks per series."""
    last = demand[PERIOD].max()
    first = last - pd.Timedelta(weeks=HISTORY_WEEKS - 1)
    forecast_date = last + pd.Timedelta(weeks=1)
    hist = demand[demand[PERIOD] >= first][KEYS + [PERIOD, "demand_units", "sold_units"]].rename(
        columns={"demand_units": "actual_units"})
    hist["is_future"] = False
    bt = backtest_pred[KEYS + [PERIOD, "h", "forecast", "baseline"]].rename(columns={"h": "horizon_week", "baseline": "baseline_units"})
    hist = hist.merge(bt, on=KEYS + [PERIOD], how="left")
    fut = future_pred[KEYS + [PERIOD, "h", "forecast"]].rename(columns={"h": "horizon_week"})
    fut["is_future"] = True
    out = pd.concat([hist, fut], ignore_index=True).merge(sigma, on=KEYS, how="left")
    out = out.rename(columns={"forecast": "forecast_units"})
    out["lower_units"] = (out.forecast_units - Z80 * out.sigma).clip(lower=0)
    out["upper_units"] = out.forecast_units + Z80 * out.sigma
    out["forecast_date"] = forecast_date
    out["model_version"] = str(model_version)
    out["scored_at"] = scored_at
    out["sold_units"] = out["sold_units"].astype(float)
    return out.sort_values(KEYS + [PERIOD]).reset_index(drop=True)


def build_stockout_risk(risk: pd.DataFrame, *, forecast_date, model_version: str, scored_at) -> pd.DataFrame:
    out = risk.copy()
    out["forecast_date"] = forecast_date
    out["model_version"] = str(model_version)
    out["scored_at"] = scored_at
    return out.sort_values(["dealer_id", "part_id", "horizon_days"]).reset_index(drop=True)
