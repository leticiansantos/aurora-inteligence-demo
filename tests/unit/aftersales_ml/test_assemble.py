import numpy as np
import pandas as pd

from aftersales.ml import assemble, forecast as fc, risk
from aftersales.ml.tables import TABLES, column_names, to_records
from test_forecast import sample


def make():
    df = sample(weeks=120).assign(sold_units=lambda d: d.demand_units, active_fleet_units=100.0)
    p = fc.Panel.from_frame(df)
    cutoff = p.weeks[-1] + pd.Timedelta(days=6) - pd.Timedelta(weeks=13)  # Sunday before holdout
    bt = fc.backtest(p, cutoff, range(1, 14))
    model = fc.fit(p, range(1, 14))
    fut = fc.predict(model, p, range(1, 9))
    return df, p, bt, fut


def test_forecast_weekly_shape_and_flags():
    df, p, bt, fut = make()
    sg = assemble.series_sigma(bt.predictions)
    assert (sg.sigma >= 0.5).all()
    fw = assemble.build_forecast_weekly(df, bt.predictions, fut, sg, model_version="7", scored_at=pd.Timestamp("2026-11-20"))
    assert len(fw) == 6 * 34
    assert fw.groupby(["dealer_id", "part_id"]).size().eq(34).all()
    h = fw[~fw.is_future]
    assert h.forecast_units.notna().sum() == 6 * 13 and h.baseline_units.notna().sum() == 6 * 13
    f = fw[fw.is_future]
    assert f.actual_units.isna().all() and f.baseline_units.isna().all() and set(f.horizon_week) == set(range(1, 9))
    assert (fw.lower_units.dropna() >= 0).all() and (fw.upper_units.dropna() >= fw.forecast_units.dropna()).all()
    assert fw.model_version.eq("7").all()
    assert not fw.duplicated(["dealer_id", "part_id", "week_start"]).any()
    to_records(fw, "aftersales_forecast_weekly")  # contract columns present


def test_risk_table_contract():
    df, p, bt, fut = make()
    sg = assemble.series_sigma(bt.predictions)
    keys = p.keys[["dealer_id", "part_id"]].assign(on_hand_units=5, on_order_units=0, lead_time_days=7)
    dealers = pd.DataFrame({"dealer_id": ["D1", "D2"], "region": ["Sul", "Sul"]})
    parts = pd.DataFrame({"part_id": ["P1", "P2", "P3"], "unit_price_brl": [10.0, 20.0, 30.0]})
    rk = risk.compute_risk(keys, parts, dealers, fut.rename(columns={"h": "horizon_week", "forecast": "forecast_units"}), sg)
    rk = assemble.build_stockout_risk(rk, forecast_date=pd.Timestamp("2026-11-16"), model_version="7", scored_at=pd.Timestamp("2026-11-20"))
    assert len(rk) == 6 * 3 and set(rk.horizon_days) == {14, 28, 56}
    assert list(rk.columns) == column_names("aftersales_stockout_risk") or set(column_names("aftersales_stockout_risk")) <= set(rk.columns)
    to_records(rk, "aftersales_stockout_risk")


def test_wape_by_category_matches_manual():
    from aftersales.ml.train import wape_by_category
    pred = pd.DataFrame({"part_id": ["P1", "P1", "P2"], "actual": [10.0, 10.0, 5.0], "forecast": [8.0, 12.0, 5.0]})
    parts = pd.DataFrame({"part_id": ["P1", "P2"], "category_id": ["a", "b"]})
    assert wape_by_category(pred, parts) == {"a": 0.2, "b": 0.0}
