"""Adversarial checks of the Aftersales API (`/api/aftersales/*`) against app/shared/aftersales.ts.

Read checks (GET only) run always. Write checks (POST, which insert rows into the Lakebase OLTP table
aftersales_replenishment_requests) run only with --write; every row QA creates carries a note starting
with "QA-T6" so it can be found and cleaned up later. The ids created are listed in the evidence.

Usage:
  python3 -I tests/aftersales/check_api.py --base http://localhost:8913 [--write] \
      [--out evidence/aftersales/api-contract.txt]
Exit code 1 when any check fails.
"""
import argparse
import concurrent.futures as cf
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

HORIZONS = [14, 28, 56]
LEVELS = ["critical", "high", "medium", "low"]
ACTIONS = {"reorder", "transfer", "monitor"}
STATUSES = {"open", "approved", "in_transit", "fulfilled", "cancelled"}
ACTIVE = {"open", "approved", "in_transit"}
TOL = 1e-6

LINES: list = []
FAILS = 0


def record(ok: bool, label: str, detail: str = ""):
    global FAILS
    FAILS += 0 if ok else 1
    LINES.append(f"{'PASS' if ok else 'FAIL'}\t{label}\t{detail}"[:600])


def call(base, method, path, body=None, raw=None, ctype="application/json"):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            txt = r.read().decode()
            return r.status, (json.loads(txt) if txt else None), dict(r.headers)
    except urllib.error.HTTPError as e:
        txt = e.read().decode()
        try:
            return e.code, json.loads(txt), dict(e.headers)
        except ValueError:
            return e.code, {"_raw": txt[:200]}, dict(e.headers)


def get(base, path, **params):
    qs = urllib.parse.urlencode(params, doseq=True)
    return call(base, "GET", path + (("?" + qs) if qs else ""))


def close(a, b, rel=1e-6, abs_=0.01):
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


def expect_400(base, label, status, body, param):
    ok = status == 400 and isinstance(body, dict) and body.get("error", {}).get("code") == "invalid_parameter" \
        and body["error"].get("param") == param
    leak = "stack" in json.dumps(body).lower() or " at " in json.dumps(body)
    record(ok and not leak, f"400 {label}", f"status={status} param={(body or {}).get('error', {}).get('param')}")


def read_checks(base):
    s, f, _ = get(base, "/api/aftersales/filters")
    record(s == 200, "GET /filters 200", f"status={s}")
    if s != 200:
        return None
    dealers = [d["id"] for d in f["dealers"]]
    cats = [c["id"] for c in f["categories"]]
    record(len(dealers) > 1 and len(set(dealers)) == len(dealers), "filters: dealers unique, >1", f"n={len(dealers)}")
    record(len(cats) > 0 and len(set(cats)) == len(cats), "filters: categories unique", f"n={len(cats)}")
    record(list(f["horizons"]) == HORIZONS and f["defaultHorizon"] == 28, "filters: horizons 14/28/56 default 28")
    m = f["meta"]
    record(m.get("synthetic") is True, "filters: meta.synthetic true")
    record(m.get("forecastDate", "") > m.get("dataThrough", ""), "meta: forecastDate > dataThrough",
           f"{m.get('dataThrough')} -> {m.get('forecastDate')}")
    record("@champion" in (m.get("modelVersion") or ""), "meta: modelVersion uses @champion", m.get("modelVersion"))

    # invalid parameters
    for path in ["/api/aftersales/summary", "/api/aftersales/forecast", "/api/aftersales/risk"]:
        for p, v in [("dealer", "NOPE"), ("dealer", ""), ("category", "nope"), ("horizon", "7"),
                     ("horizon", "abc"), ("horizon", "14.0"), ("dealer", dealers[0].lower())]:
            s, b, _ = get(base, path, **{p: v})
            expect_400(base, f"{path} {p}={v!r}", s, b, p)
        s, b, _ = get(base, path, dealer=[dealers[0], dealers[1]])
        expect_400(base, f"{path} repeated dealer", s, b, "dealer")
    for v in ["0", "201", "-1", "x", "1.5"]:
        s, b, _ = get(base, "/api/aftersales/risk", limit=v)
        expect_400(base, f"/risk limit={v}", s, b, "limit")
    s, b, _ = get(base, "/api/aftersales/risk", minLevel="severe")
    expect_400(base, "/risk minLevel=severe", s, b, "minLevel")
    s, b, _ = get(base, "/api/aftersales/forecast", partId="NOPE")
    record(s in (400, 404) or (s == 200 and not any(p["actualUnits"] for p in b["series"])),
           "/forecast unknown partId rejected or empty", f"status={s}")

    # consistency per selection
    selections = [{}] + [{"dealer": d} for d in dealers[:3]] + [{"category": c} for c in cats[:2]] \
        + [{"dealer": dealers[0], "category": cats[0]}]
    for sel in selections:
        for h in HORIZONS:
            q = dict(sel, horizon=h)
            tag = ",".join(f"{k}={v}" for k, v in q.items())
            s1, sm, _ = get(base, "/api/aftersales/summary", **q)
            s2, rk, _ = get(base, "/api/aftersales/risk", **q, limit=200)
            if s1 != 200 or s2 != 200:
                record(False, f"[{tag}] summary/risk 200", f"{s1}/{s2}")
                continue
            k, dist, rows = sm["kpis"], sm["riskDistribution"], rk["rows"]
            record(sm["meta"]["query"] == {"dealer": sel.get("dealer"), "category": sel.get("category"), "horizon": h},
                   f"[{tag}] meta.query echoes applied params", json.dumps(sm["meta"]["query"]))
            record(k["partsAtRisk"]["value"] == dist["critical"] + dist["high"], f"[{tag}] partsAtRisk == critical+high",
                   f"{k['partsAtRisk']['value']} vs {dist}")
            record(sum(dist.values()) == rk["total"], f"[{tag}] sum(riskDistribution) == /risk total",
                   f"{sum(dist.values())} vs {rk['total']}")
            record(k["fillRate"]["value"] is None or 0 <= k["fillRate"]["value"] <= 1, f"[{tag}] fillRate is a fraction or null", str(k["fillRate"]["value"]))
            for name in ["partsAtRisk", "lostSalesAvoidedBrl", "fillRate", "daysOfStock"]:
                record(k[name]["previous"] is None or isinstance(k[name]["previous"], (int, float)),
                       f"[{tag}] {name}.previous null or number")
            record(len(rows) == min(200, rk["total"]), f"[{tag}] /risk rows == min(limit,total)", f"{len(rows)}/{rk['total']}")
            order = [(-r["lostSalesBrl"], -r["stockoutProbability"], r["key"]) for r in rows]
            record(order == sorted(order), f"[{tag}] /risk sorted lostSales desc, prob desc, key asc")
            bad = []
            for r in rows:
                if r["key"] != f"{r['dealerId']}:{r['partId']}":
                    bad.append(("key", r["key"]))
                if sel.get("dealer") and r["dealerId"] != sel["dealer"]:
                    bad.append(("dealer filter", r["key"]))
                if sel.get("category") and r["categoryId"] != sel["category"]:
                    bad.append(("category filter", r["key"]))
                if r["action"] not in ACTIONS or r["riskLevel"] not in LEVELS:
                    bad.append(("enum", r["key"]))
                if not (0 <= r["stockoutProbability"] <= 1):
                    bad.append(("prob range", r["key"]))
                if (r["action"] == "monitor") != (r["recommendedQty"] == 0):
                    bad.append(("monitor<->qty0", r["key"]))
                if (r["action"] == "transfer") != (r["transferFrom"] is not None):
                    bad.append(("transferFrom iff transfer", r["key"]))
                if r["transferFrom"]:
                    t = r["transferFrom"]
                    if t["dealerId"] == r["dealerId"] or t["availableUnits"] < r["recommendedQty"]:
                        bad.append(("transfer donor", r["key"]))
                    if t["dealerId"] not in dealers:
                        bad.append(("transfer donor unknown", r["key"]))
                if r["stockUnits"] < 0 or r["forecastUnits"] < 0 or r["lostSalesBrl"] < 0:
                    bad.append(("negative", r["key"]))
                fd = r["forecastUnits"] / h
                dos = None if fd == 0 else r["stockUnits"] / fd
                if not close(r["daysOfStock"], dos, rel=1e-3, abs_=0.05):
                    bad.append(("daysOfStock", r["key"], r["daysOfStock"], dos))
                if r["openRequest"] and r["openRequest"]["status"] not in ACTIVE:
                    bad.append(("openRequest status", r["key"]))
            record(not bad, f"[{tag}] /risk row invariants ({len(rows)} rows)", str(bad[:5]))
            if rk["total"] <= 200:
                avoided = sum(r["lostSalesBrl"] for r in rows if r["action"] != "monitor")
                record(close(k["lostSalesAvoidedBrl"]["value"], avoided, rel=1e-6, abs_=1.0),
                       f"[{tag}] lostSalesAvoided == sum(lostSales, action!=monitor)",
                       f"{k['lostSalesAvoidedBrl']['value']} vs {avoided:.2f}")
                st = sum(r["stockUnits"] for r in rows)
                fu = sum(r["forecastUnits"] for r in rows)
                dos = None if fu == 0 else st / (fu / h)
                record(close(k["daysOfStock"]["value"], dos, rel=1e-3, abs_=0.05),
                       f"[{tag}] daysOfStock == sum(stock)/(sum(fc)/h)", f"{k['daysOfStock']['value']} vs {dos}")
            # level filter monotonic
            s3, rk2, _ = get(base, "/api/aftersales/risk", **q, minLevel="high", limit=200)
            if s3 == 200:
                record(rk2["total"] == dist["critical"] + dist["high"] and all(r["riskLevel"] in ("critical", "high") for r in rk2["rows"]),
                       f"[{tag}] minLevel=high total == critical+high", f"{rk2['total']}")
        # forecast series per selection (horizon-independent)
        s, fc, _ = get(base, "/api/aftersales/forecast", **sel)
        if s == 200:
            ser = fc["series"]
            weeks = [p["weekStart"] for p in ser]
            fdate = fc["meta"]["forecastDate"]
            bad = [p for p in ser if datetime.strptime(p["weekStart"], "%Y-%m-%d").weekday() != 0]
            record(not bad and weeks == sorted(set(weeks)), f"[{sel}] /forecast weeks are unique Mondays ascending", f"n={len(ser)}")
            fut = [p for p in ser if p["isFuture"]]
            record(len(fut) == 8 and len(ser) == 34, f"[{sel}] /forecast has 26 history + 8 future weeks", f"{len(fut)}")
            record(all((p["weekStart"] >= fdate) == p["isFuture"] for p in ser), f"[{sel}] isFuture == weekStart>=forecastDate")
            record(all(p["actualUnits"] is None for p in fut), f"[{sel}] no actuals in future weeks")
            record(all(p["forecastUnits"] is None or (p["lowerUnits"] <= p["forecastUnits"] <= p["upperUnits"]) for p in ser),
                   f"[{sel}] lower <= forecast <= upper")
            acc = fc["accuracy"]
            record(acc is None or (acc["wape"] >= 0 and acc["baselineWape"] >= 0), f"[{sel}] accuracy sane", json.dumps(acc))
            # recompute WAPE over past points that have both actual and forecast (backtest window shown)
            past = [p for p in ser if not p["isFuture"] and p["forecastUnits"] is not None and p["actualUnits"] is not None]
            if acc and past:
                LINES.append(f"INFO\t[{sel}] chart-level WAPE over {len(past)} backtest weeks="
                             f"{sum(abs(p['actualUnits'] - p['forecastUnits']) for p in past) / max(1, sum(p['actualUnits'] for p in past)):.4f}"
                             f" (API wape={acc['wape']:.4f}, computed at dealer×part grain so it can be larger)")
        else:
            record(False, f"[{sel}] /forecast 200", f"status={s}")
    return dealers, cats


def write_checks(base, dealers):
    created = []
    s, rk, _ = get(base, "/api/aftersales/risk", limit=200)
    rows = rk["rows"] if s == 200 else []
    target = next((r for r in rows if r["openRequest"] is None and r["action"] == "reorder"), None) \
        or next((r for r in rows if r["openRequest"] is None), None)
    if not target:
        record(False, "write: found a dealer×part with no active request")
        return created
    d, p = target["dealerId"], target["partId"]
    other = next(x for x in dealers if x != d)
    base_body = {"dealerId": d, "partId": p, "type": "reorder", "quantity": 5}
    path = "/api/aftersales/requests"

    # validation matrix (none of these may create a row)
    cases = [("quantity", dict(base_body, quantity=v)) for v in [0, -1, 1.5, "5", 100001, None]] + [
        ("dealerId", dict(base_body, dealerId="NOPE")),
        ("partId", dict(base_body, partId="NOPE")),
        ("type", dict(base_body, type="steal")),
        ("fromDealerId", dict(base_body, fromDealerId=other)),
        ("fromDealerId", dict(base_body, type="transfer")),
        ("fromDealerId", dict(base_body, type="transfer", fromDealerId=d)),
        ("fromDealerId", dict(base_body, type="transfer", fromDealerId="NOPE")),
        ("note", dict(base_body, note="x" * 501)),
        ("note", dict(base_body, note="a\u0000b")),
        ("isAdmin", dict(base_body, isAdmin=True)),
    ]
    for param, body in cases:
        s, b, _ = call(base, "POST", path, body)
        expect_400(base, f"POST {param}={json.dumps(body.get(param))[:30]}", s, b, param)
    s, b, _ = call(base, "POST", path, raw=b"{not json", ctype="application/json")
    expect_400(base, "POST malformed JSON", s, b, "body")
    s, b, _ = call(base, "POST", path, raw=json.dumps(base_body).encode(), ctype="text/plain")
    expect_400(base, "POST text/plain", s, b, "body")
    s, b, _ = call(base, "POST", path, raw=json.dumps(dict(base_body, note="y" * 20000)).encode())
    record(s in (400, 413), "POST 20 KB body rejected", f"status={s}")

    # duplicate race: 10 parallel identical POSTs -> 1x201, 9x409
    body = dict(base_body, note="  QA-T6 race  ")
    with cf.ThreadPoolExecutor(10) as ex:
        res = list(ex.map(lambda _: call(base, "POST", path, body), range(10)))
    codes = sorted(r[0] for r in res)
    record(codes.count(201) == 1 and codes.count(409) == 9, "POST 10 parallel duplicates -> 1x201 9x409", str(codes))
    ok = [r for r in res if r[0] == 201]
    dup = [r for r in res if r[0] == 409]
    if dup:
        record(dup[0][1].get("error", {}).get("code") == "duplicate_request", "409 code duplicate_request")
    if not ok:
        return created
    st, rb, hdr = ok[0]
    req = rb["request"]
    created.append(req["id"])
    record(hdr.get("Location") == f"{path}/{req['id']}", "201 Location header", hdr.get("Location", ""))
    record(req["status"] == "open" and req["requestedBy"] == "local-dev" and req["note"] == "QA-T6 race"
           and req["quantity"] == 5 and req["fromDealerId"] is None, "201 body: open/local-dev/trimmed note", json.dumps(req)[:300])
    record(req["horizonDays"] == 28 and req["riskLevel"] == target["riskLevel"]
           and close(req["lostSalesBrl"], target["lostSalesBrl"], abs_=0.005), "201 body: snapshot of the default-horizon risk row",
           f"{req['horizonDays']} {req['riskLevel']} {req['lostSalesBrl']} vs {target['riskLevel']} {target['lostSalesBrl']}")
    try:
        uuid.UUID(req["id"])
        record(True, "id is a UUID")
    except ValueError:
        record(False, "id is a UUID", req["id"])
    s, one, _ = get(base, f"{path}/{req['id']}")
    record(s == 200 and one["request"] == req, "GET /requests/:id == POST body", f"status={s}")
    s, lst, _ = get(base, path, dealer=d)
    record(s == 200 and lst["requests"] and lst["requests"][0]["id"] == req["id"], "GET /requests newest first includes it")
    stamps = [r["createdAt"] for r in lst["requests"]] if s == 200 else []
    record(stamps == sorted(stamps, reverse=True), "GET /requests sorted createdAt desc")
    s, rk, _ = get(base, "/api/aftersales/risk", dealer=d, limit=200)
    row = next((r for r in rk["rows"] if r["partId"] == p), None) if s == 200 else None
    record(row is not None and row["openRequest"] == {"id": req["id"], "status": "open", "type": "reorder"},
           "/risk openRequest reflects the new request", json.dumps(row and row["openRequest"]))
    # a different type for the same pair is allowed (unique key includes type), only if donor exists
    if target.get("transferFrom"):
        tb = {"dealerId": d, "partId": p, "type": "transfer", "quantity": 1,
              "fromDealerId": target["transferFrom"]["dealerId"], "note": "QA-T6 transfer"}
        s, b, _ = call(base, "POST", path, tb)
        record(s == 201, "POST transfer for same pair (different type) allowed", f"status={s}")
        if s == 201:
            created.append(b["request"]["id"])
        tb2 = dict(tb, quantity=target["transferFrom"]["availableUnits"] + 1, partId=p)
        s, b, _ = call(base, "POST", path, tb2)
        record(s in (400, 409), "POST transfer qty > donor available rejected", f"status={s}")
    # explicit transfer cases, independent of what /risk recommends
    s, rk_all, _ = get(base, "/api/aftersales/risk", limit=200)
    rows_all = rk_all["rows"] if s == 200 else []
    pair = next(((r, dn) for r in rows_all if r["openRequest"] is None or r["openRequest"]["type"] != "transfer"
                 for dn in rows_all if dn["partId"] == r["partId"] and dn["dealerId"] != r["dealerId"] and dn["stockUnits"] > 0), None)
    if pair:
        r, dn = pair
        tb = {"dealerId": r["dealerId"], "partId": r["partId"], "type": "transfer", "fromDealerId": dn["dealerId"],
              "quantity": dn["stockUnits"] + 1, "note": "QA-T6 transfer over donor stock"}
        s, b, _ = call(base, "POST", path, tb)
        expect_400(base, "POST transfer qty = donor stock + 1", s, b, "quantity")
        tb.update(quantity=1, note="QA-T6 transfer")
        s, b, _ = call(base, "POST", path, tb)
        ok = s == 201 and b["request"]["fromDealerId"] == dn["dealerId"] and b["request"]["type"] == "transfer"
        record(ok, "POST valid transfer (qty 1 from a donor with stock) 201", f"status={s}")
        if s == 201:
            created.append(b["request"]["id"])
    else:
        record(False, "found a dealer pair for transfer tests")
    # filters / id validation
    for v in ["", "x"]:
        s, b, _ = get(base, path, status=v or "bogus")
        expect_400(base, f"GET /requests status={v or 'bogus'}", s, b, "status")
    s, b, _ = get(base, f"{path}/not-a-uuid")
    expect_400(base, "GET /requests/not-a-uuid", s, b, "id")
    s, b, _ = get(base, f"{path}/{uuid.uuid4()}")
    record(s == 404 and b.get("error", {}).get("code") == "not_found", "GET /requests/<random uuid> 404", f"status={s}")
    s, b, _ = get(base, f"{path}/" + urllib.parse.quote("' OR 1=1 --", safe=""))
    record(s == 400, "GET /requests/<sql injection> 400", f"status={s}")
    return created


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--out", default="evidence/aftersales/api-contract.txt")
    a = ap.parse_args()
    res = read_checks(a.base)
    created = write_checks(a.base, res[0]) if (a.write and res) else []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    head = ["# claim:   /api/aftersales/* follows app/shared/aftersales.ts (validation, invariants, sort, request round-trip)",
            f"# command: python3 -I tests/aftersales/check_api.py --base <local server>{' --write' if a.write else ''}",
            f"# date:    {now}  qa git: {sha}",
            f"# result:  {'PASS' if FAILS == 0 else f'FAIL ({FAILS})'}  checks={sum(1 for l in LINES if not l.startswith('INFO'))}",
            f"# created request ids (note starts with QA-T6): {created}", ""]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(head + LINES) + "\n", encoding="utf-8")
    print("\n".join(head + [l for l in LINES if not l.startswith("PASS")]))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
