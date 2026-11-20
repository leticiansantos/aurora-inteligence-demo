import math

import pandas as pd

from aftersales.ml.risk import compute_risk, days_to_stockout, phi


def build(stock_rows, fc=10.0, sigma=2.0, price=100.0):
    stock = pd.DataFrame(stock_rows, columns=["dealer_id", "on_hand_units", "on_order_units", "lead_time_days"])
    stock["part_id"] = "P1"
    dealers = pd.DataFrame({"dealer_id": stock.dealer_id, "region": "Sul"})
    parts = pd.DataFrame({"part_id": ["P1"], "unit_price_brl": [price]})
    future = pd.DataFrame([(d, "P1", k, fc) for d in stock.dealer_id for k in range(1, 9)],
                          columns=["dealer_id", "part_id", "horizon_week", "forecast_units"])
    sg = pd.DataFrame({"dealer_id": stock.dealer_id, "part_id": "P1", "sigma": sigma})
    return compute_risk(stock, parts, dealers, future, sg)


def row(df, d, h=28):
    return df[(df.dealer_id == d) & (df.horizon_days == h)].iloc[0]


def test_days_to_stockout():
    assert days_to_stockout([7.0] * 8, 3.5) == 4   # 1 unit/day -> 4th day exceeds 3.5
    assert days_to_stockout([0.0] * 8, 5) is None
    assert days_to_stockout([7.0] * 8, 0) == 1


def test_days_to_stockout_no_float_drift():
    # 13/week with 13 available: day-by-day accumulation gives 13.000000000000002 > 13 on day 7 (wrong)
    assert days_to_stockout([13.0] * 8, 13) == 8


def test_phi():
    assert abs(phi(0) - 0.5) < 1e-12


def test_formulas_and_levels():
    r = row(build([("D1", 5, 0, 7)]), "D1")
    assert r.forecast_units == 40.0 and r.available_units == 5
    assert math.isclose(r.forecast_sigma_units, 2 * 2)
    assert math.isclose(r.safety_stock_units, 1.65 * 2 * 1.0)
    assert r.shortfall_units == math.ceil(40 + 3.3 - 5)
    assert r.days_to_stockout == 4 and r.risk_level == "critical"      # 4 <= min(28, 7)
    assert math.isclose(r.lost_sales_brl, 35 * 100)
    assert math.isclose(r.days_of_stock, 5 / (40 / 28))


def test_levels_high_medium_low():
    # lead 3: stockout day 4 > lead but <= horizon -> high
    assert row(build([("D1", 5, 0, 3)]), "D1").risk_level == "high"
    # enough for 28 days of demand but short on safety stock -> medium
    assert row(build([("D1", 40, 0, 7)]), "D1").risk_level in ("medium", "high")
    assert row(build([("D1", 500, 0, 7)]), "D1").risk_level == "low"


def test_zero_sigma_probability():
    r = row(build([("D1", 5, 0, 7)], sigma=0.0), "D1")
    assert r.stockout_probability in (0.0, 1.0)


def test_transfer_and_reorder_greedy():
    # fc=10/wk, sigma=2, lead 7 -> H=4: mu=40, safety=3.3. shortfall(stock 0)=ceil(43.3)=44.
    # D3 (200): excess = min(200, floor(200-43.3)) = 156. D4 (60): excess = min(60, floor(16.7)) = 16.
    df = build([("D1", 0, 0, 7), ("D2", 0, 0, 7), ("D3", 200, 0, 7), ("D4", 60, 0, 7)])
    d1, d2 = row(df, "D1"), row(df, "D2")
    assert (d1.shortfall_units, d2.shortfall_units) == (44, 44)
    assert (d1.action, d1.transfer_from_dealer_id, d1.transfer_from_excess_units, d1.recommended_qty) == ("transfer", "D3", 156, 44)
    # equal lost sales/probability -> D1 first (dealer asc); D3 then has 156-44 = 112 left, still the largest
    assert (d2.action, d2.transfer_from_dealer_id, d2.transfer_from_excess_units, d2.recommended_qty) == ("transfer", "D3", 112, 44)
    d3, d4 = row(df, "D3"), row(df, "D4")
    assert d3.action == "monitor" and d3.recommended_qty == 0 and d3.transfer_from_dealer_id is None
    assert d4.action == "monitor"


def test_no_partial_transfer_falls_back_to_reorder():
    # only donor has excess 16 < shortfall 44 -> reorder the whole gap, donor untouched
    df = build([("D1", 0, 0, 7), ("D4", 60, 0, 7)])
    r = row(df, "D1")
    assert r.action == "reorder" and r.recommended_qty == 44 and r.transfer_from_dealer_id is None


def test_donor_tie_breaks_on_dealer_id():
    df = build([("D1", 0, 0, 7), ("D5", 100, 0, 7), ("D2", 100, 0, 7)])
    assert row(df, "D1").transfer_from_dealer_id == "D2"


def test_donor_limited_by_on_hand():
    # available = on_hand + on_order, but only on-hand can move
    df = build([("D1", 0, 0, 7), ("D2", 10, 500, 7)])
    assert row(df, "D1").action == "reorder"
