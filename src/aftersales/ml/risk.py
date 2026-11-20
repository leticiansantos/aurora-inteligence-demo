"""Stockout risk and recommendations: exact implementation of ADR D5 (the QA oracle diffs this row by row).

Pure Python/pandas. Inputs:
  stock   : dealer_id, part_id, on_hand_units, on_order_units, lead_time_days
  parts   : part_id, unit_price_brl
  dealers : dealer_id, region
  future  : dealer_id, part_id, horizon_week (1..8), forecast_units
  sigma   : dealer_id, part_id, sigma  (max(holdout RMSE, 0.5))
"""
from __future__ import annotations

import math

import pandas as pd

HORIZONS_DAYS = (14, 28, 56)
Z95 = 1.65
MAX_DAYS = 56


def phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def r6(x: float) -> float:
    """ADR D5 numeric rule: round to 6 decimals before any comparison, ceil or floor."""
    return round(x, 6)


def days_to_stockout(weekly: list[float], available: float) -> int | None:
    """Smallest n in 1..56 with cum(n) > available, else None.

    Closed form (no day-by-day accumulation drift): cum(n) = sum_{k<w} f_k + (n - 7(w-1)) * f_w / 7, w = ceil(n/7).
    """
    for n in range(1, MAX_DAYS + 1):
        w = math.ceil(n / 7)
        cum = 0.0
        for k in range(w - 1):
            cum += weekly[k]
        cum += (n - 7 * (w - 1)) * weekly[w - 1] / 7.0
        if r6(cum) > available:
            return n
    return None


def risk_level(dts: int | None, horizon: int, lead: int, shortfall: int) -> str:
    if dts is not None and dts <= min(horizon, lead):
        return "critical"
    if dts is not None and dts <= horizon:
        return "high"
    return "medium" if shortfall > 0 else "low"


def compute_risk(stock: pd.DataFrame, parts: pd.DataFrame, dealers: pd.DataFrame, future: pd.DataFrame,
                 sigma: pd.DataFrame) -> pd.DataFrame:
    weekly = {k: g.sort_values("horizon_week")["forecast_units"].astype(float).tolist()
              for k, g in future.groupby(["dealer_id", "part_id"])}
    sig = {(r.dealer_id, r.part_id): float(r.sigma) for r in sigma.itertuples()}
    price = dict(zip(parts.part_id, parts.unit_price_brl))
    region = dict(zip(dealers.dealer_id, dealers.region))
    rows = []
    for r in stock.sort_values(["dealer_id", "part_id"]).itertuples():
        f = weekly[(r.dealer_id, r.part_id)]
        s = sig[(r.dealer_id, r.part_id)]
        available = int(r.on_hand_units) + int(r.on_order_units)
        lead = int(r.lead_time_days)
        dts = days_to_stockout(f, available)
        for D in HORIZONS_DAYS:
            H = D // 7
            mu = 0.0
            for k in range(H):
                mu += f[k]
            sd = s * math.sqrt(H)
            safety = Z95 * s * math.sqrt(lead / 7.0)
            if sd == 0:
                prob = 1.0 if mu > available else 0.0
            else:
                prob = 1.0 - phi((available - mu) / sd)
            shortfall = int(math.ceil(r6(max(0.0, mu + safety - available))))
            rows.append(dict(
                dealer_id=r.dealer_id, part_id=r.part_id, horizon_days=D, stock_units=int(r.on_hand_units),
                on_order_units=int(r.on_order_units), available_units=available, lead_time_days=lead,
                forecast_units=mu, forecast_sigma_units=sd, safety_stock_units=safety,
                days_of_stock=(r.on_hand_units / (mu / D)) if mu > 0 else None,
                days_to_stockout=dts, stockout_probability=prob,
                risk_level=risk_level(dts, D, lead, shortfall), shortfall_units=shortfall,
                lost_sales_brl=max(0.0, mu - available) * float(price[r.part_id]),
                region=region[r.dealer_id]))
    out = pd.DataFrame(rows)
    return recommend(out)


def recommend(risk: pd.DataFrame) -> pd.DataFrame:
    """Greedy, deterministic, independent per horizon (ADR D5 'Recomendação')."""
    risk = risk.copy()
    risk["action"] = "monitor"
    risk["recommended_qty"] = 0
    risk["transfer_from_dealer_id"] = None
    risk["transfer_from_excess_units"] = None
    risk["excess_tmp"] = [
        min(int(oh), math.floor(r6(av - mu - ss)))
        for oh, av, mu, ss in zip(risk.stock_units, risk.available_units, risk.forecast_units, risk.safety_stock_units)]
    for (_, _, _), g in risk.groupby(["horizon_days", "part_id", "region"]):
        remaining = {r.dealer_id: int(r.excess_tmp) for r in g.itertuples() if r.excess_tmp > 0}
        needy = g[g.shortfall_units > 0].sort_values(
            ["lost_sales_brl", "stockout_probability", "dealer_id", "part_id"], ascending=[False, False, True, True])
        for r in needy.itertuples():
            donor = None
            for did in sorted(remaining):  # dealer_id asc, so max() keeps the smallest id on ties
                if donor is None or remaining[did] > remaining[donor]:
                    donor = did
            sf = int(r.shortfall_units)
            risk.loc[r.Index, "recommended_qty"] = sf
            if donor is not None and remaining[donor] >= sf:
                risk.loc[r.Index, ["action", "transfer_from_dealer_id", "transfer_from_excess_units"]] = [
                    "transfer", donor, remaining[donor]]
                remaining[donor] -= sf
            else:
                risk.loc[r.Index, "action"] = "reorder"
    return risk.drop(columns=["excess_tmp", "region"])
