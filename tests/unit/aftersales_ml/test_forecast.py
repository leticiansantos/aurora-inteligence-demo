import numpy as np
import pandas as pd

from aftersales.ml.forecast import KEYS, PERIOD, Panel, backtest, bias, seasonal_naive, wape


def sample(weeks=200, seed=1):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2022-01-03", periods=weeks, freq="7D")
    rows = []
    for dealer in ("D1", "D2"):
        for part in ("P1", "P2", "P3"):
            base = rng.uniform(5, 30)
            for i, d in enumerate(dates):
                seas = 1 + 0.4 * np.sin(2 * np.pi * d.isocalendar().week / 52)
                rows.append((dealer, part, d, rng.poisson(base * seas * (1 + 0.003 * i))))
    return pd.DataFrame(rows, columns=["dealer_id", "part_id", PERIOD, "demand_units"])


def test_metrics():
    assert wape([10, 10], [8, 12]) == 0.2
    assert np.isnan(wape([0, 0], [1, 1]))
    assert bias([10, 10], [12, 12]) == 0.2


def test_seasonal_naive_uses_same_week_last_year():
    p = Panel.from_frame(sample())
    fc = seasonal_naive(p, [1, 2])
    t = p.y.shape[1] - 1
    row = fc[(fc.h == 1)].iloc[0]
    assert row.baseline == p.y[0, t + 1 - 52]


def test_no_leakage_into_training_window():
    p = Panel.from_frame(sample().assign(active_fleet_units=lambda d: np.arange(len(d)) % 50.0))
    cutoff = p.weeks[-13] - pd.Timedelta(days=1)
    r = backtest(p, cutoff, range(1, 13))
    assert r.predictions[PERIOD].min() > cutoff
    # changing the future must not change predictions
    p2 = Panel(p.keys, p.weeks, p.y.copy(), p.fleet.copy())
    p2.y[:, -13:] += 1000
    p2.fleet[:, -13:] += 1000
    r2 = backtest(p2, cutoff, range(1, 13))
    np.testing.assert_allclose(r.predictions.forecast.values, r2.predictions.forecast.values)


def test_backtest_deterministic_and_beats_baseline():
    p = Panel.from_frame(sample())
    cutoff = p.weeks[-13] - pd.Timedelta(days=1)
    a, b = backtest(p, cutoff, range(1, 14)), backtest(p, cutoff, range(1, 14))
    assert a.wape_model == b.wape_model
    assert a.wape_model < a.wape_baseline
    assert a.n_series == 6 and set(a.wape_by_h) == set(range(1, 14))


def test_bad_cutoff_is_rejected():
    import pytest
    p = Panel.from_frame(sample())
    with pytest.raises(ValueError):
        backtest(p, p.weeks[-13], range(1, 13))   # a Monday: would leak one week
