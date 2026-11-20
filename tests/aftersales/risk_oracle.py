"""Independent re-implementation of ADR 002 D5 (stockout risk + recommendation), diffed row by row against
`aftersales_stockout_risk`. Inputs are read with SELECTs only: stock_position, parts, dealers and
forecast_weekly (future weeks and holdout, for sigma). Nothing is read from the risk table except to compare.

Usage:
  python3 -I tests/aftersales/risk_oracle.py --profile classic-stable-new --warehouse 754bcdfc4beaaaa1 \
      [--catalog classic_stable --schema auto_intelligence] [--out evidence/aftersales/risk/oracle-diff.txt]
Exit code 1 on any mismatch.
"""
import argparse
import json
import math
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HORIZONS = [14, 28, 56]
Z_SS = 1.65


def sql(a, stmt):
    res = subprocess.run(["databricks", "experimental", "aitools", "tools", "query", "-p", a.profile, "-w", a.warehouse,
                          "-o", "json", stmt], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip()[-400:])
    return json.loads(res.stdout or "[]")


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def compute(stock, price, region, fut, sigma):
    """stock[(d,p)] = (on_hand, on_order, lead); fut[(d,p)] = [f1..f8]; sigma[(d,p)] = σ."""
    out = {}
    for D in HORIZONS:
        H = D // 7
        rows = {}
        for key, (on_hand, on_order, L) in stock.items():
            d, p = key
            f = fut[key]
            s = sigma[key]
            avail = on_hand + on_order
            mu = 0.0
            for k in range(H):  # ADR D5 numeric rule: sum f_k in order k = 1..H
                mu += f[k]
            sig_h = s * math.sqrt(H)
            ss = Z_SS * s * math.sqrt(L / 7)
            dos = None if mu == 0 else on_hand / (mu / D)
            dts = None
            for n in range(1, 57):  # closed form cum(n) = sum_{k<w} f_k + (n - 7(w-1)) f_w / 7, w = ceil(n/7)
                w = math.ceil(n / 7)
                cum = sum(f[:w - 1]) + (n - 7 * (w - 1)) * f[w - 1] / 7
                if round(cum, 6) > avail:
                    dts = n
                    break
            if sig_h == 0:
                prob = 1.0 if mu > avail else 0.0
            else:
                prob = 1 - phi((avail - mu) / sig_h)
            short = math.ceil(round(max(0.0, mu + ss - avail), 6))
            lost = max(0.0, mu - avail) * price[p]
            if dts is not None and dts <= min(D, L):
                lvl = "critical"
            elif dts is not None and dts <= D:
                lvl = "high"
            elif short > 0:
                lvl = "medium"
            else:
                lvl = "low"
            excess = min(on_hand, math.floor(round(avail - mu - ss, 6)))  # ADR 64213a5: only on-hand stock moves
            rows[key] = dict(stock_units=on_hand, on_order_units=on_order, available_units=avail, lead_time_days=L,
                             forecast_units=mu, forecast_sigma_units=sig_h, safety_stock_units=ss, days_of_stock=dos,
                             days_to_stockout=dts, stockout_probability=prob, risk_level=lvl, shortfall_units=short,
                             lost_sales_brl=lost, action="monitor" if short == 0 else None, recommended_qty=0,
                             transfer_from_dealer_id=None, transfer_from_excess_units=None, _excess=excess,
                             _donor_on_hand=on_hand)
        remaining = {k: r["_excess"] for k, r in rows.items() if r["_excess"] > 0}
        todo = sorted((k for k, r in rows.items() if r["shortfall_units"] > 0),
                      key=lambda k: (-rows[k]["lost_sales_brl"], -rows[k]["stockout_probability"], k[0], k[1]))
        for k in todo:
            d, p = k
            r = rows[k]
            donors = [(x, e) for (x, pp), e in remaining.items() if pp == p and x != d and region[x] == region[d] and e > 0]
            best = min(donors, key=lambda t: (-t[1], t[0])) if donors else None
            r["recommended_qty"] = r["shortfall_units"]
            if best and best[1] >= r["shortfall_units"]:
                r["action"] = "transfer"
                r["transfer_from_dealer_id"] = best[0]
                r["transfer_from_excess_units"] = best[1]
                remaining[(best[0], p)] -= r["shortfall_units"]
            else:
                r["action"] = "reorder"
        for k, r in rows.items():
            out[(k[0], k[1], D)] = r
    return out


def same(a, b, rel=1e-6, abs_=1e-6):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, str) or isinstance(b, str):
        return str(a) == str(b)
    return abs(float(a) - float(b)) <= max(abs_, rel * max(abs(float(a)), abs(float(b))))


def num(v):
    if v is None or v == "":  # the CLI JSON output renders SQL NULL as ""
        return None
    if isinstance(v, (int, float)):
        return v
    if v in ("true", "false"):
        return v == "true"
    try:
        return float(v)
    except ValueError:
        return v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--warehouse", required=True)
    ap.add_argument("--catalog", default="classic_stable")
    ap.add_argument("--schema", default="auto_intelligence")
    ap.add_argument("--out", default="evidence/aftersales/risk/oracle-diff.txt")
    a = ap.parse_args()
    T = f"{a.catalog}.{a.schema}."
    stock = {(r["dealer_id"], r["part_id"]): (int(r["on_hand_units"]), int(r["on_order_units"]), int(r["lead_time_days"]))
             for r in sql(a, f"SELECT dealer_id, part_id, on_hand_units, on_order_units, lead_time_days FROM {T}aftersales_stock_position")}
    price = {r["part_id"]: float(r["unit_price_brl"]) for r in sql(a, f"SELECT part_id, unit_price_brl FROM {T}aftersales_parts")}
    region = {r["dealer_id"]: r["region"] for r in sql(a, f"SELECT dealer_id, region FROM {T}aftersales_dealers")}
    fut = defaultdict(lambda: [None] * 8)
    for r in sql(a, f"SELECT dealer_id, part_id, horizon_week, forecast_units FROM {T}aftersales_forecast_weekly WHERE is_future"):
        fut[(r["dealer_id"], r["part_id"])][int(r["horizon_week"]) - 1] = float(r["forecast_units"])
    sigma = {(r["dealer_id"], r["part_id"]): max(float(r["rmse"]), 0.5) for r in sql(a, f"""
        SELECT dealer_id, part_id, sqrt(avg(pow(actual_units - forecast_units, 2))) rmse FROM {T}aftersales_forecast_weekly
        WHERE NOT is_future AND forecast_units IS NOT NULL GROUP BY ALL""")}
    lines, fails = [], 0
    incomplete = [k for k in stock if k not in fut or None in fut[k] or k not in sigma]
    if incomplete:
        lines.append(f"FAIL\tinputs complete\t{len(incomplete)} series without 8 future weeks or holdout sigma, e.g. {incomplete[:3]}")
        fails += 1
    exp = compute({k: v for k, v in stock.items() if k not in incomplete}, price, region, fut, sigma)
    got = {(r["dealer_id"], r["part_id"], int(r["horizon_days"])): {k: num(v) for k, v in r.items()}
           for r in sql(a, f"SELECT * FROM {T}aftersales_stockout_risk")}
    fields = ["stock_units", "on_order_units", "available_units", "lead_time_days", "forecast_units", "forecast_sigma_units",
              "safety_stock_units", "days_of_stock", "days_to_stockout", "stockout_probability", "risk_level",
              "shortfall_units", "lost_sales_brl", "action", "recommended_qty", "transfer_from_dealer_id",
              "transfer_from_excess_units"]
    missing = sorted(set(exp) - set(got))
    extra = sorted(set(got) - set(exp))
    lines.append(f"{'PASS' if not missing and not extra else 'FAIL'}\tsame keys (dealer, part, horizon)\texpected={len(exp)} got={len(got)} missing={missing[:5]} extra={extra[:5]}")
    fails += 0 if not missing and not extra else 1
    per_field = defaultdict(list)
    for k in sorted(set(exp) & set(got)):
        for fld in fields:
            if not same(exp[k][fld], got[k].get(fld)):
                per_field[fld].append((k, exp[k][fld], got[k].get(fld)))
    for fld in fields:
        bad = per_field.get(fld, [])
        fails += 1 if bad else 0
        lines.append(f"{'PASS' if not bad else 'FAIL'}\t{fld}\tmismatches={len(bad)}" + (f" e.g. {bad[:3]}" if bad else ""))
    # meta columns
    meta = sql(a, f"""SELECT count(DISTINCT forecast_date) nfd, max(forecast_date) fd, count(DISTINCT model_version) nmv,
                      max(model_version) mv, (SELECT max(model_version) FROM {T}aftersales_model_metrics WHERE is_champion) champ
                      FROM {T}aftersales_stockout_risk""")[0]
    ok = meta["nfd"] in (1, "1") and str(meta["fd"]) == "2026-11-16" and meta["nmv"] in (1, "1") and meta["mv"] == meta["champ"]
    fails += 0 if ok else 1
    lines.append(f"{'PASS' if ok else 'FAIL'}\tforecast_date 2026-11-16 and model_version == champion\t{json.dumps(meta)}")
    # D1 plausibility targets at h=28, and INFO on the donor-on-hand rule
    h28 = [r for k, r in exp.items() if k[2] == 28]
    ch = sum(r["risk_level"] in ("critical", "high") for r in h28) / max(1, len(h28))
    ntr = sum(r["action"] == "transfer" for r in h28)
    # Original D1 target 3..12% is reported as a FINDING (INFO, not a failure) because ADR 002 3a6e17f records the
    # measured 14.2% as an accepted deviation and revises the target to 3..15%, which is the hard check.
    lines.append(f"{'INFO' if 0.03 <= ch <= 0.12 else 'FINDING'}\toriginal D1 target critical+high 3%..12% at h=28"
                 f"\t{ch:.3%} ({sum(r['risk_level'] in ('critical', 'high') for r in h28)}/{len(h28)})"
                 + ("" if 0.03 <= ch <= 0.12 else " -> deviation accepted in ADR D1 (3a6e17f)"))
    for ok, label, det in [(0.03 <= ch <= 0.15, "D1 target (revised, ADR 3a6e17f): critical+high 3%..15% at h=28", f"{ch:.3%}"),
                           (ntr >= 10, "D1 target: >= 10 transfer recommendations at h=28", f"{ntr}")]:
        fails += 0 if ok else 1
        lines.append(f"{'PASS' if ok else 'FAIL'}\t{label}\t{det}")
    dist = defaultdict(int)
    for k, r in exp.items():
        dist[(k[2], r["risk_level"], r["action"])] += 1
    lines.append("INFO\tdistribution (horizon, level, action) -> rows\t" + json.dumps({f"{h}|{l}|{ac}": n for (h, l, ac), n in sorted(dist.items())}))
    over = [(k, r["recommended_qty"], stock[(r["transfer_from_dealer_id"], k[1])][0]) for k, r in got.items()
            if r["action"] == "transfer" and r["recommended_qty"] > stock[(r["transfer_from_dealer_id"], k[1])][0]]
    fails += 1 if over else 0
    lines.append(f"{'FAIL' if over else 'PASS'}\tno transfer exceeds the donor on_hand\t{len(over)} e.g. {over[:3]}")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    head = ["# claim:   aftersales_stockout_risk == independent re-implementation of ADR 002 D5 (all 2160 rows, every field)",
            f"# command: python3 -I tests/aftersales/risk_oracle.py --catalog {a.catalog} --schema {a.schema}",
            f"# date:    {now}  qa git: {sha}",
            f"# result:  {'PASS' if fails == 0 else f'FAIL ({fails})'}", ""]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(head + lines) + "\n", encoding="utf-8")
    print("\n".join(head + lines))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
