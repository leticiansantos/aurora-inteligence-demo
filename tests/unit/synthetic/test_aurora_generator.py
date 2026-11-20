import os
import sys
from dataclasses import replace
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src", "market", "synthetic"))

from aurora_config import DEFAULT_CONFIG as CFG  # noqa: E402
from aurora_generator import generate_rows  # noqa: E402

COLUMNS = ["ref_month", "segment", "brand", "model", "units", "target_share",
           "is_synthetic", "generator_version", "seed"]


def make_totals(start=(2018, 1), end=(2025, 12)):
    out, y, m = [], *start
    while (y, m) <= end:
        out.append((date(y, m, 1), 200_000 + ((y * 12 + m) * 7919) % 60_000))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


TOTALS = make_totals()


def by_month(rows):
    d = {}
    for r in rows:
        d.setdefault(r["ref_month"], []).append(r)
    return d


def test_deterministic_and_order_independent():
    assert generate_rows(TOTALS) == generate_rows(TOTALS)
    assert generate_rows(TOTALS) == generate_rows(list(reversed(TOTALS)))


def test_no_rows_before_launch():
    rows = generate_rows(TOTALS)
    assert rows and min(r["ref_month"] for r in rows) == date(2019, 1, 1)
    assert all(r["ref_month"].year != 2018 for r in rows)


def test_share_bounds_per_period():
    totals = dict(TOTALS)
    for month, rs in by_month(generate_rows(TOTALS)).items():
        aurora = sum(r["units"] for r in rs)
        real = totals[month]
        share = aurora / (real + aurora)
        tol = 1 / (real + aurora)
        lo = 0.03 if month >= date(2022, 1, 1) else 0.0
        assert lo - tol <= share <= 0.04 + tol
        assert lo <= rs[0]["target_share"] <= 0.04
        assert abs(share - rs[0]["target_share"]) <= tol


def test_ramp_reaches_three_percent():
    rows = by_month(generate_rows(TOTALS))
    assert rows[date(2019, 1, 1)][0]["target_share"] == 0
    assert rows[date(2022, 1, 1)][0]["target_share"] >= 0.03


def test_model_units_sum_to_total():
    totals = dict(TOTALS)
    for month, rs in by_month(generate_rows(TOTALS)).items():
        share = rs[0]["target_share"]
        assert sum(r["units"] for r in rs) == round(share * totals[month] / (1 - share))
        assert all(isinstance(r["units"], int) and r["units"] >= 0 for r in rs)


def test_models_and_constants():
    rows = generate_rows(TOTALS)
    assert {r["model"] for r in rows} == {"IPE", "JATOBA", "AROEIRA"}
    assert all(len(rs) == 3 for rs in by_month(rows).values())
    assert {r["brand"] for r in rows} == {"AURORA MOTORS"}
    assert {r["segment"] for r in rows} == {"automoveis"}
    assert {r["is_synthetic"] for r in rows} == {True}
    assert {r["generator_version"] for r in rows} == {"aurora-gen-1.0.0"}
    assert {r["seed"] for r in rows} == {20190101}


def test_empty_totals():
    assert generate_rows([]) == []


def test_only_pre_launch_totals():
    assert generate_rows(make_totals((2018, 1), (2018, 12))) == []


def test_seed_change_changes_output():
    assert generate_rows(TOTALS) != generate_rows(TOTALS, replace(CFG, seed=42))


def test_schema_columns_and_order():
    assert all(list(r.keys()) == COLUMNS for r in generate_rows(TOTALS))
    r = generate_rows(TOTALS)[-1]
    assert isinstance(r["ref_month"], date) and isinstance(r["target_share"], float)
    assert isinstance(r["seed"], int) and isinstance(r["is_synthetic"], bool)


def test_unique_primary_key():
    rows = generate_rows(TOTALS)
    keys = {(r["ref_month"], r["segment"], r["brand"], r["model"]) for r in rows}
    assert len(keys) == len(rows)


def _spark_semantics(totals, cfg=CFG):
    """Python emulation of the lazy Spark logic in market_synthetic_registrations.py (join curve, rint,
    floor + largest remainder by window)."""
    import math
    from collections import defaultdict
    from aurora_generator import curve_rows
    by_month = defaultdict(list)
    for ref, model, tie, share, w in curve_rows(cfg):
        by_month[ref].append((model, tie, share, w))
    out = {}
    for ref, total in totals:
        if ref not in by_month or total is None or total < 0:
            continue
        rows = by_month[ref]
        share = rows[0][2]
        aurora_total = int(round(share * total / (1 - share)))  # rint == half-even
        raws = [(m, t, aurora_total * w) for m, t, _, w in rows]
        base = {m: math.floor(r) for m, t, r in raws}
        order = sorted(raws, key=lambda x: (-(x[2] - math.floor(x[2])), x[1]))
        rem = aurora_total - sum(base.values())
        for rn, (m, _, _) in enumerate(order, start=1):
            out[(ref, m)] = base[m] + (1 if rn <= rem else 0)
    return out


def test_curve_formula_reproduces_generate_rows():
    from aurora_generator import curve_rows
    months = [date(2018, 12, 1), date(2019, 1, 1), date(2019, 7, 1), date(2021, 3, 1), date(2022, 1, 1),
              date(2023, 6, 1), date(2025, 11, 1), date(2026, 9, 1)]
    totals = [(m, 195_000 + 4_321 * i) for i, m in enumerate(months)]
    expected = {(r["ref_month"], r["model"]): r["units"] for r in generate_rows(totals)}
    assert _spark_semantics(totals) == expected
    curve = curve_rows()
    assert curve[0][0] == CFG.launch_date and len({c[1] for c in curve}) == 3
    assert abs(sum(c[4] for c in curve if c[0] == date(2023, 6, 1)) - 1.0) < 1e-12
