"""Demand forecasting core: seasonal-naive baseline, global direct multi-horizon model, time-based backtest.

Pure pandas/numpy/scikit-learn so it runs locally and on serverless. Weekly grain, one series per
(dealer_id, part_id). Direct strategy: a single HistGradientBoostingRegressor receives features observed at the
forecast origin plus the horizon h, and predicts y[origin + h]. No recursion, so no error compounding.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

KEYS = ["dealer_id", "part_id"]
PERIOD = "week_start"
TARGET = "demand_units"
SEASON = 52
SEED = 42
STATIC_COLS = ["part_category_code", "is_critical", "region_code"]  # numeric codes, see encode_static()
FEATURES = ["h", "y_0", "y_1", "y_2", "y_3", "m4", "m13", "m52", "y_seas", "y_seas_prev", "y_seas_next",
            "woy_target", "month_target", "fleet"] + STATIC_COLS


def wape(actual, predicted) -> float:
    """sum|a-p| / sum|a|. Robust to zeros, unlike MAPE."""
    a, p = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    d = np.abs(a).sum()
    return float("nan") if d == 0 else float(np.abs(a - p).sum() / d)


def bias(actual, predicted) -> float:
    """sum(p-a) / sum(a): positive = over-forecast."""
    a, p = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    d = a.sum()
    return float("nan") if d == 0 else float((p - a).sum() / d)


@dataclass
class Panel:
    """Dense series x weeks matrix. Missing weeks are zero demand (no sale recorded)."""
    keys: pd.DataFrame      # one row per series (KEYS + static cols)
    weeks: pd.DatetimeIndex
    y: np.ndarray           # shape (n_series, n_weeks)
    fleet: np.ndarray | None = None  # same shape; active fleet of the dealer in the month of each week

    @classmethod
    def from_frame(cls, df: pd.DataFrame, *, last_week=None, static: pd.DataFrame | None = None,
                   fleet_col: str = "active_fleet_units") -> "Panel":
        last = pd.Timestamp(last_week) if last_week is not None else df[PERIOD].max()
        df = df[df[PERIOD] <= last]
        weeks = pd.date_range(df[PERIOD].min(), last, freq="7D")
        piv = df.pivot_table(index=KEYS, columns=PERIOD, values=TARGET, aggfunc="sum").reindex(columns=weeks).fillna(0.0)
        keys = piv.index.to_frame(index=False)
        if static is not None:
            keys = keys.merge(static, on=KEYS, how="left")
        for c in STATIC_COLS:
            if c not in keys:
                keys[c] = 0.0
        fleet = None
        if fleet_col in df:
            fleet = (df.pivot_table(index=KEYS, columns=PERIOD, values=fleet_col, aggfunc="max")
                     .reindex(index=piv.index, columns=weeks).ffill(axis=1).fillna(0.0).to_numpy(dtype=float))
        return cls(keys, weeks, piv.to_numpy(dtype=float), fleet)

    def truncate(self, last_week) -> "Panel":
        n = int((self.weeks <= pd.Timestamp(last_week)).sum())
        return Panel(self.keys, self.weeks[:n], self.y[:, :n], None if self.fleet is None else self.fleet[:, :n])


def encode_static(parts: pd.DataFrame, dealers: pd.DataFrame) -> pd.DataFrame:
    """Per-series numeric static features. Codes come from the sorted unique values, so they are deterministic."""
    cat = {v: i for i, v in enumerate(sorted(parts["category_id"].unique()))}
    reg = {v: i for i, v in enumerate(sorted(dealers["region"].unique()))}
    d = dealers[["dealer_id", "region"]].assign(region_code=lambda x: x.region.map(reg).astype(float))
    p = parts[["part_id", "category_id", "is_critical"]].assign(
        part_category_code=lambda x: x.category_id.map(cat).astype(float), is_critical=lambda x: x.is_critical.astype(float))
    return d.merge(p, how="cross")[KEYS + STATIC_COLS]


def _col(y: np.ndarray, idx: np.ndarray | int) -> np.ndarray:
    """y[:, idx] with out-of-range (negative) positions -> NaN."""
    idx = np.atleast_1d(idx)
    out = np.full((y.shape[0], len(idx)), np.nan)
    ok = (idx >= 0) & (idx < y.shape[1])
    out[:, ok] = y[:, idx[ok]]
    return out


def features_at(panel: Panel, t: int, h: int, weeks_target: pd.Timestamp) -> pd.DataFrame:
    """Feature rows for every series at origin index t (last observed week) and horizon h."""
    y, cs = panel.y, np.concatenate([np.zeros((panel.y.shape[0], 1)), np.cumsum(panel.y, axis=1)], axis=1)

    def roll(n):  # mean of the last n weeks up to and including t
        lo = max(0, t + 1 - n)
        return (cs[:, t + 1] - cs[:, lo]) / (t + 1 - lo)

    seas = t + h - SEASON  # same week last year, aligned with the target week
    f = pd.DataFrame({
        "h": h,
        "y_0": y[:, t],
        "y_1": _col(y, t - 1)[:, 0], "y_2": _col(y, t - 2)[:, 0], "y_3": _col(y, t - 3)[:, 0],
        "m4": roll(4), "m13": roll(13), "m52": roll(52),
        "y_seas": _col(y, seas)[:, 0], "y_seas_prev": _col(y, seas - 1)[:, 0], "y_seas_next": _col(y, seas + 1)[:, 0],
        "woy_target": int(weeks_target.isocalendar().week), "month_target": weeks_target.month,
        # fleet observed at the origin week only (never the target month): no leakage
        "fleet": panel.fleet[:, t] if panel.fleet is not None else 0.0,
    })
    for c in STATIC_COLS:
        f[c] = panel.keys[c].to_numpy()
    for c in KEYS:
        f[c] = panel.keys[c].to_numpy()
    return f


def training_set(panel: Panel, horizons, *, origin_stride: int = 2, max_origins: int = 156) -> pd.DataFrame:
    """Rows (origin, h) whose target week is inside the panel. Strided/capped to bound memory."""
    n = panel.y.shape[1]
    parts = []
    for h in horizons:
        last_origin = n - 1 - h
        origins = range(max(SEASON, last_origin - max_origins * origin_stride), last_origin + 1, origin_stride)
        for t in origins:
            wt = panel.weeks[t] + pd.Timedelta(weeks=h)
            f = features_at(panel, t, h, wt)
            f[TARGET] = panel.y[:, t + h]
            parts.append(f)
    return pd.concat(parts, ignore_index=True)


def fit(panel: Panel, horizons, *, seed: int = SEED, **kw) -> HistGradientBoostingRegressor:
    tr = training_set(panel, horizons, **kw)
    model = HistGradientBoostingRegressor(loss="poisson", max_iter=250, learning_rate=0.06, max_leaf_nodes=24,
                                          min_samples_leaf=40, l2_regularization=1.0, early_stopping=False, random_state=seed)
    model.fit(tr[FEATURES], tr[TARGET])
    return model


def predict(model, panel: Panel, horizons) -> pd.DataFrame:
    """Forecast from the panel's last week for each h. Returns KEYS, week_start, h, forecast."""
    t = panel.y.shape[1] - 1
    out = []
    for h in horizons:
        wt = panel.weeks[t] + pd.Timedelta(weeks=h)
        f = features_at(panel, t, h, wt)
        f["forecast"] = np.clip(model.predict(f[FEATURES]), 0, None)
        f[PERIOD] = wt
        out.append(f[KEYS + [PERIOD, "h", "forecast"]])
    return pd.concat(out, ignore_index=True)


def seasonal_naive(panel: Panel, horizons) -> pd.DataFrame:
    """y_hat[t+h] = y[t+h-52]. No fallback: the history must cover the lag (fails loudly otherwise)."""
    t = panel.y.shape[1] - 1
    out = []
    for h in horizons:
        lag = _col(panel.y, t + h - SEASON)[:, 0]
        if np.isnan(lag).any():
            raise ValueError(f"seasonal-naive needs {SEASON + 1 - h}+ weeks of history; panel has {t + 1}")
        f = panel.keys[KEYS].copy()
        f[PERIOD] = panel.weeks[t] + pd.Timedelta(weeks=h)
        f["h"] = h
        f["baseline"] = lag
        out.append(f)
    return pd.concat(out, ignore_index=True)


@dataclass
class BacktestResult:
    wape_model: float
    wape_baseline: float
    bias_model: float
    bias_baseline: float
    cutoff: pd.Timestamp
    horizons: list
    n_series: int
    predictions: pd.DataFrame = field(repr=False)  # KEYS, week_start, h, actual, forecast, baseline
    wape_by_h: dict = field(default_factory=dict)

    @property
    def lift(self) -> float:
        """Relative WAPE reduction vs baseline (positive = model better)."""
        return 1 - self.wape_model / self.wape_baseline

    def passes_gate(self, factor: float = 0.95) -> bool:
        return self.wape_model < self.wape_baseline * factor


def backtest(panel: Panel, cutoff, horizons=range(1, 14), **kw) -> BacktestResult:
    """Train only on data up to `cutoff` (targets included), forecast h=1..H from the cutoff, compare with actuals."""
    horizons = list(horizons)
    cutoff = pd.Timestamp(cutoff)
    if cutoff.day_of_week != 6:
        raise ValueError(f"cutoff {cutoff.date()} must be a Sunday (end of the last training week)")
    train = panel.truncate(cutoff)
    if train.weeks[-1] != cutoff - pd.Timedelta(days=6):
        raise ValueError(f"last training origin {train.weeks[-1].date()} != {(cutoff - pd.Timedelta(days=6)).date()}")
    model = fit(train, horizons, **kw)
    pred = predict(model, train, horizons).merge(seasonal_naive(train, horizons), on=KEYS + [PERIOD, "h"])
    n_s, n_w = panel.y.shape
    actual = pd.DataFrame({
        **{c: np.repeat(panel.keys[c].to_numpy(), n_w) for c in KEYS},
        PERIOD: np.tile(panel.weeks.to_numpy(), n_s), "actual": panel.y.ravel()})
    pred = pred.merge(actual, on=KEYS + [PERIOD], how="inner")
    by_h = {int(h): wape(g.actual, g.forecast) for h, g in pred.groupby("h")}
    first = pred[PERIOD].min()
    if first != cutoff + pd.Timedelta(days=1) or pred[PERIOD].nunique() != len(horizons):
        raise ValueError(f"holdout must be {len(horizons)} weeks starting {(cutoff + pd.Timedelta(days=1)).date()}, "
                         f"got {pred[PERIOD].nunique()} starting {first.date()}")
    return BacktestResult(wape(pred.actual, pred.forecast), wape(pred.actual, pred.baseline),
                          bias(pred.actual, pred.forecast), bias(pred.actual, pred.baseline),
                          pd.Timestamp(cutoff), horizons, len(panel.keys), pred, by_h)
