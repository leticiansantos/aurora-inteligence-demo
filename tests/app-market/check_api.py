"""Adversarial check of the Market API (/api/market/*) against direct SQL on the gold tables.

Every API number is compared with an independent SQL oracle (tests/app-market/sql/*.sql), which reads
market_segment_totals / market_brand_monthly / market_model_monthly directly and never the share_* tables
the server may use. Output is TEXT: one line per check with the API value and the SQL value side by side.

Real brand and model names are masked (BRAND_<sha6>, MODEL_<sha6>); Aurora Motors (fictional), its models
and the residual row are kept. Stdlib only.

Usage: python3 -I tests/app-market/check_api.py --base http://localhost:8903 --profile <p> --warehouse <id>
       [--months 2026-09-01,2023-03-01,2007-06-01,2004-01-01] [--out evidence/app-market/api-vs-sql.txt]
Exit 1 when any check FAILs.
"""
import argparse
import concurrent.futures as cf
import csv
import hashlib
import io
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

SQL_DIR = Path(__file__).resolve().parent / "sql"
SEGMENTS = ["automoveis", "comerciais_leves", "total"]
VIEWS = ["real", "with_aurora"]
PERIODS = {"12m": 12, "24m": 24, "60m": 60, "all": None}
FIRST_MONTH = "2003-01-01"
RESIDUAL = "OUTRAS (NAO PUBLICADAS)"
AURORA = "AURORA MOTORS"
AURORA_MODELS = {"IPE", "JATOBA", "AROEIRA"}
TOL = 1e-9

ARGS = None
LINES: list[str] = []
FAILS = 0


# ---------- helpers ----------

def mask(kind: str, name):
    if name is None or name in (RESIDUAL, AURORA) or (kind == "MODEL" and name in AURORA_MODELS):
        return name
    return f"{kind}_" + hashlib.sha256(str(name).encode("utf-8")).hexdigest()[:6]


def add_months(d: str, n: int) -> str:
    y, m = int(d[:4]), int(d[5:7]) - 1 + n
    return date(y + m // 12, m % 12 + 1, 1).isoformat()


def num(v):
    if v is None or v == "":
        return None
    f = float(v)
    return int(f) if f.is_integer() and "." not in str(v) and "E" not in str(v).upper() else f


def same(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= TOL
    return a == b


def check(label: str, api, sql, ok=None):
    global FAILS
    passed = same(api, sql) if ok is None else ok
    FAILS += 0 if passed else 1
    LINES.append(f"{'PASS' if passed else 'FAIL'}  {label:<78} api={api!r:<24} sql={sql!r}")
    return passed


def section(title: str):
    LINES.append("")
    LINES.append(f"## {title}")


def sql(file: str, **params):
    cmd = ["databricks", "experimental", "aitools", "tools", "query", "--profile", ARGS.profile,
           "--warehouse", ARGS.warehouse, "--output", "csv", str(SQL_DIR / file)]
    for k, v in params.items():
        cmd += ["--param", f"{k}:DATE={v}" if k in ("month", "from", "to") else f"{k}={v}"]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        raise RuntimeError(f"{file} {params}: {out.stderr.strip()[:300]}")
    rows = list(csv.DictReader(io.StringIO(out.stdout)))
    return [{k: (num(v) if k not in ("brand", "model", "month", "is_synthetic", "is_residual") else v)
             for k, v in r.items()} for r in rows]


def api(path: str, **params):
    url = f"{ARGS.base}/api/market/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            return e.code, json.loads(body)
        except ValueError:
            return e.code, {"raw": body[:200].decode("utf-8", "replace")}


def raw_api(query: str):
    """GET with a hand-built query string (repeated params etc.)."""
    url = f"{ARGS.base}/api/market/{query}"
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except ValueError:
            return e.code, {}


def tf(v: str) -> bool:
    return str(v).lower() == "true"


# ---------- checks ----------

def check_summary(month: str, seg: str, view: str, s_api, o):
    tag = f"summary {month[:7]} {seg} {view}"
    st, body = s_api
    if not check(f"{tag} http", st, 200):
        LINES.append(f"      body={json.dumps(body)[:200]}")
        return None
    m = body["market"]
    o = o[0]
    check(f"{tag} month", body["month"], month)
    check(f"{tag} meta.query", body["meta"]["query"], {"segment": seg, "period": body["meta"]["query"].get("period"),
                                                       "view": view, "month": month})
    check(f"{tag} previousYearMonth", body["previousYearMonth"], add_months(month, -12))
    check(f"{tag} market.realUnits", m["realUnits"], o["real_units"])
    aurora_applies = view == "with_aurora" and o["aurora_units"] is not None
    check(f"{tag} market.auroraUnits", m["auroraUnits"], o["aurora_units"] if aurora_applies else None)
    check(f"{tag} market.totalUnits", m["totalUnits"], o["total_units"])
    check(f"{tag} market.previousYearUnits", m["previousYearUnits"], o["previous_year_units"])
    check(f"{tag} market.yoyPct", m["yoyPct"], o["yoy_pct"])
    a = body["aurora"]
    if not aurora_applies:
        check(f"{tag} aurora (expect null)", a, None)
    else:
        if check(f"{tag} aurora present", a is not None, True):
            check(f"{tag} aurora.units", a["units"], o["aurora_units"])
            check(f"{tag} aurora.share", a["share"], o["aurora_share"])
            check(f"{tag} aurora.rank", a["rank"], o["aurora_rank"])
            check(f"{tag} aurora.rankedBrands", a["rankedBrands"], o["ranked_brands"])
            check(f"{tag} aurora.previousYearShare", a["previousYearShare"], o["aurora_previous_year_share"])
            check(f"{tag} aurora.shareChangePp", a["shareChangePp"], o["aurora_share_change_pp"])
    return body


def check_brand_list(tag: str, lst, oracle, limit: int):
    if lst is None:
        check(f"{tag} list present", None, "list")
        return
    tot = oracle[0]["total_units"] if oracle else 0
    check(f"{tag} totalUnits", lst["totalUnits"], tot)
    by_brand = {r["brand"]: r for r in oracle}
    rows = lst["rows"]
    nonres = [r for r in rows if not r["isResidual"]]
    res = [r for r in rows if r["isResidual"]]
    o_nonres = [r for r in oracle if not tf(r["is_residual"])]
    o_res = [r for r in oracle if tf(r["is_residual"])]
    check(f"{tag} non-residual rows = min(limit, brands)", len(nonres), min(limit, len(o_nonres)))
    exp_res = o_res and o_res[0]["units"] > 0
    check(f"{tag} residual row present iff residual>0", len(res), 1 if exp_res else 0)
    if res:
        check(f"{tag} residual is last row", rows[-1]["isResidual"], True)
        check(f"{tag} residual rank null", res[0]["rank"], None)
        check(f"{tag} residual label", res[0]["label"], "Outras (não publicadas)")
        check(f"{tag} residual units", res[0]["units"], o_res[0]["units"])
        check(f"{tag} residual share", res[0]["share"], o_res[0]["share"])
    bad = []
    for r in nonres:
        o = by_brand.get(r["brand"])
        if o is None:
            bad.append(f"{mask('BRAND', r['brand'])}: not in SQL")
            continue
        for k_api, k_sql in (("units", "units"), ("share", "share"), ("rank", "dense_rnk")):
            if not same(r[k_api], o[k_sql]):
                bad.append(f"{mask('BRAND', r['brand'])}.{k_api} api={r[k_api]} sql={o[k_sql]}")
        if r["isAurora"] != (r["brand"] == AURORA):
            bad.append(f"{mask('BRAND', r['brand'])}.isAurora={r['isAurora']}")
        if r["isAurora"] and r["label"] != "Aurora Motors":
            bad.append(f"aurora label={r['label']!r}")
    check(f"{tag} every brand row units/share/dense_rank == SQL ({len(nonres)} rows)",
          "; ".join(bad[:4]) or "ok", "ok")
    units = [r["units"] for r in nonres]
    check(f"{tag} rows sorted by units desc", units == sorted(units, reverse=True), True)
    shown = {r["brand"] for r in nonres}
    cut = [o for o in o_nonres if o["brand"] not in shown]
    check(f"{tag} othersUnits = sum(cut brands)", lst["othersUnits"], sum(o["units"] for o in cut))
    if cut and units:
        check(f"{tag} no cut brand outsells a shown one", max(o["units"] for o in cut) <= min(units), True)
    check(f"{tag} sum(rows.units)+othersUnits == totalUnits",
          sum(r["units"] for r in rows) + lst["othersUnits"], lst["totalUnits"])
    if lst["totalUnits"]:
        check(f"{tag} sum(rows.share)+others/total == 1",
              sum(r["share"] for r in rows) + lst["othersUnits"] / lst["totalUnits"], 1.0)
    if "view=real" in tag:
        check(f"{tag} no Aurora row in view real", any(r["isAurora"] for r in rows), False)


def check_models(month: str, seg: str, view: str, m_api, oracle, oracle_month: str, limit: int):
    tag = f"models {month[:7]} {seg} {view}"
    st, body = m_api
    if not check(f"{tag} http", st, 200):
        LINES.append(f"      body={json.dumps(body)[:200]}")
        return
    check(f"{tag} month (shown)", body["month"], oracle_month)
    check(f"{tag} latestMonth (requested)", body["latestMonth"], month)
    check(f"{tag} available", body["available"], bool(oracle))
    if not oracle:
        check(f"{tag} rows empty", len(body["rows"]), 0)
        return
    check(f"{tag} coveredUnits", body["coveredUnits"], oracle[0]["covered_units"])
    check(f"{tag} totalUnits", body["totalUnits"], oracle[0]["total_units"])
    check(f"{tag} coveredUnits < totalUnits (no model residual)", body["coveredUnits"] < body["totalUnits"], True)
    rows = body["rows"]
    check(f"{tag} row count", len(rows), min(limit, len(oracle)))
    bad = []
    for r, o in zip(rows, oracle):
        for k_api, k_sql in (("rank", "row_num"), ("brand", "brand"), ("model", "model"), ("units", "units"),
                             ("share", "share")):
            if not same(r[k_api], o[k_sql]):
                kind = {"brand": "BRAND", "model": "MODEL"}.get(k_api)
                a_v, s_v = (mask(kind, r[k_api]), mask(kind, o[k_sql])) if kind else (r[k_api], o[k_sql])
                bad.append(f"#{o['row_num']}.{k_api} api={a_v} sql={s_v}")
        if r["isAurora"] != tf(o["is_synthetic"]):
            bad.append(f"#{o['row_num']}.isAurora")
    check(f"{tag} rows == SQL row_number order ({len(rows)} rows)", "; ".join(bad[:4]) or "ok", "ok")
    if view == "real":
        check(f"{tag} no Aurora model in view real", any(r["isAurora"] for r in rows), False)


def check_timeseries(seg: str, view: str, period: str, ts_api, oracle_all, latest: str):
    tag = f"timeseries {seg} {view} {period}"
    st, body = ts_api
    if not check(f"{tag} http", st, 200):
        return None
    n = PERIODS[period]
    frm = FIRST_MONTH if n is None else add_months(latest, -(n - 1))
    exp = [o for o in oracle_all if o["month"] >= frm]
    check(f"{tag} from", body["from"], frm)
    check(f"{tag} to", body["to"], latest)
    pts = body["points"]
    check(f"{tag} point count", len(pts), len(exp))
    bad = []
    for p, o in zip(pts, exp):
        for k_api, k_sql in (("month", "month"), ("realUnits", "real_units"), ("auroraUnits", "aurora_units"),
                             ("totalUnits", "total_units"), ("auroraShare", "aurora_share")):
            if not same(p[k_api], o[k_sql]):
                bad.append(f"{o['month'][:7]}.{k_api} api={p[k_api]} sql={o[k_sql]}")
    check(f"{tag} every point == SQL", "; ".join(bad[:4]) or "ok", "ok")
    return body


def check_validation():
    section("Input validation (expect 400 + error.code=invalid_parameter + error.param)")
    cases = [
        ("summary?segment=AUTOMOVEIS", "segment"), ("summary?segment=", "segment"),
        ("summary?segment=automoveis&segment=total", "segment"), ("summary?view=aurora", "view"),
        ("summary?period=36m", "period"), ("timeseries?period=", "period"),
        ("summary?month=2002-12", "month"), ("summary?month=2026-10", "month"),
        ("summary?month=2026-13", "month"), ("summary?month=2023-03-15", "month"),
        ("summary?month=2023-3", "month"), ("summary?month=abc", "month"),
        ("brands?limit=0", "limit"), ("brands?limit=26", "limit"), ("brands?limit=1.5", "limit"),
        ("brands?limit=abc", "limit"), ("brands?limit=-1", "limit"), ("models?limit=51", "limit"),
        ("models?limit=", "limit"), ("brands?segment=total%27%20OR%201%3D1--", "segment"),
        ("models?month=2023-03%27--", "month"),
    ]
    for q, param in cases:
        st, body = raw_api(q)
        err = body.get("error", {}) if isinstance(body, dict) else {}
        ok = st == 400 and err.get("code") == "invalid_parameter" and err.get("param") == param
        check(f"GET /api/market/{q}", f"{st} {err.get('code')} {err.get('param')}", f"400 invalid_parameter {param}",
              ok=ok)
        leak = json.dumps(body)
        check(f"  no stack/secret in body", any(s in leak for s in ("at /", "node_modules", "dapi", "Bearer")), False)
    for q in ("summary?foo=bar", "brands?limit=25", "brands?limit=1", "models?limit=50", "summary?month=2023-03-01",
              "summary?month=2003-01", "timeseries?month=2023-03"):
        st, _ = raw_api(q)
        check(f"GET /api/market/{q} accepted", st, 200)


def main() -> int:
    global ARGS
    p = argparse.ArgumentParser()
    p.add_argument("--base", required=True)
    p.add_argument("--profile", required=True)
    p.add_argument("--warehouse", required=True)
    p.add_argument("--months", default="latest,2023-03-01,2007-06-01,2004-01-01")
    p.add_argument("--out", default="evidence/app-market/api-vs-sql.txt")
    ARGS = p.parse_args()

    st, s0 = api("summary")
    if st != 200:
        print(f"server not ready: {st} {s0}", file=sys.stderr)
        return 2
    latest = s0["coverage"]["lastMonth"]
    months = [latest if m == "latest" else m for m in ARGS.months.split(",")]
    section(f"Defaults and coverage (latest month from API = {latest})")
    check("summary defaults meta.query", s0["meta"]["query"],
          {"segment": "total", "period": "24m", "view": "with_aurora", "month": latest})
    check("coverage.firstMonth", s0["coverage"]["firstMonth"], FIRST_MONTH)
    check("coverage.monthsCount", s0["coverage"]["monthsCount"],
          sql("02_timeseries.sql", **{"from": FIRST_MONTH, "to": latest, "segment": "total", "view": "real"}).__len__())

    combos = [(m, s, v) for m in months for s in SEGMENTS for v in VIEWS]
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        f_sum = {c: ex.submit(sql, "01_summary.sql", month=c[0], segment=c[1], view=c[2]) for c in combos}
        f_bm = {c: ex.submit(sql, "03_brands.sql", **{"from": c[0], "to": c[0], "segment": c[1], "view": c[2]})
                for c in combos}
        f_bp = {c: ex.submit(sql, "03_brands.sql", **{"from": add_months(c[0], -23), "to": c[0], "segment": c[1],
                                                      "view": c[2]}) for c in combos}
        f_ts = {(s, v): ex.submit(sql, "02_timeseries.sql", **{"from": FIRST_MONTH, "to": latest, "segment": s,
                                                              "view": v}) for s in SEGMENTS for v in VIEWS}
        # models: the shown month is the closest month <= requested that has a model table
        model_month = {}
        for m in months:
            mm = m
            while mm >= FIRST_MONTH:
                if sql("04_models.sql", month=mm, segment="total", view="real"):
                    break
                mm = add_months(mm, -1)
            model_month[m] = mm
        f_mo = {c: ex.submit(sql, "04_models.sql", month=model_month[c[0]], segment=c[1], view=c[2]) for c in combos}
        a_sum = {c: ex.submit(api, "summary", month=c[0], segment=c[1], view=c[2]) for c in combos}
        a_br = {c: ex.submit(api, "brands", month=c[0], segment=c[1], view=c[2], period="24m", limit=25)
                for c in combos}
        a_mo = {c: ex.submit(api, "models", month=c[0], segment=c[1], view=c[2], limit=50) for c in combos}
        a_ts = {(s, v, per): ex.submit(api, "timeseries", segment=s, view=v, period=per)
                for s in SEGMENTS for v in VIEWS for per in PERIODS}

        sums = {}
        for c in combos:
            section(f"Summary {c[0][:7]} {c[1]} {c[2]}")
            sums[c] = check_summary(*c, a_sum[c].result(), f_sum[c].result())
        for c in combos:
            section(f"Brands {c[0][:7]} {c[1]} view={c[2]} (limit=25, period=24m)")
            st, body = a_br[c].result()
            if not check(f"brands {c[0][:7]} {c[1]} {c[2]} http", st, 200):
                continue
            check_brand_list(f"brands month {c[0][:7]} {c[1]} view={c[2]}", body.get("latestMonth"),
                             f_bm[c].result(), 25)
            check(f"brands period from", body["period"]["from"], max(FIRST_MONTH, add_months(c[0], -23)))
            check_brand_list(f"brands 24m->{c[0][:7]} {c[1]} view={c[2]}", body.get("period"), f_bp[c].result(), 25)
        for c in combos:
            section(f"Models {c[0][:7]} {c[1]} {c[2]} (limit=50; SQL shown month {model_month[c[0]][:7]})")
            check_models(*c, a_mo[c].result(), f_mo[c].result(), model_month[c[0]], 50)
        ts = {}
        for s in SEGMENTS:
            for v in VIEWS:
                section(f"Timeseries {s} {v}")
                for per in PERIODS:
                    ts[(s, v, per)] = check_timeseries(s, v, per, a_ts[(s, v, per)].result(), f_ts[(s, v)].result(),
                                                       latest)

    section("Aurora toggle never changes the real market total")
    for m in months:
        for s in SEGMENTS:
            r, w = sums.get((m, s, "real")), sums.get((m, s, "with_aurora"))
            if r and w:
                check(f"summary {m[:7]} {s} realUnits real==with_aurora", r["market"]["realUnits"],
                      w["market"]["realUnits"])
                check(f"summary {m[:7]} {s} view real: totalUnits==realUnits", r["market"]["totalUnits"],
                      r["market"]["realUnits"])
    for s in SEGMENTS:
        r, w = ts.get((s, "real", "all")), ts.get((s, "with_aurora", "all"))
        if r and w:
            diff = [a["month"] for a, b in zip(r["points"], w["points"]) if a["realUnits"] != b["realUnits"]]
            check(f"timeseries {s} all: realUnits identical across views", diff[:3] or "none", "none")
            pre = [b["month"] for b in w["points"] if b["month"] < "2019-01-01" and b["auroraUnits"] is not None]
            check(f"timeseries {s} with_aurora: auroraUnits null before 2019-01", pre[:3] or "none", "none")
            if s == "comerciais_leves":
                cl = [b["month"] for b in w["points"] if b["auroraUnits"] is not None]
                check("timeseries comerciais_leves with_aurora: auroraUnits always null", cl[:3] or "none", "none")
    for m in months:
        st, b = api("summary", month=m, segment="total", view="real")
        st2, t = api("timeseries", segment="total", view="real", period="all")
        if st == 200 and st2 == 200:
            pt = next((x for x in t["points"] if x["month"] == m), None)
            check(f"summary {m[:7]} total realUnits == timeseries point", b["market"]["realUnits"],
                  pt and pt["realUnits"])

    check_validation()

    head = [f"# Market API vs SQL oracle — {ARGS.base} — months {', '.join(months)}",
            f"# checks: {len([l for l in LINES if l[:4] in ('PASS', 'FAIL')])}  FAIL: {FAILS}",
            "# brand/model names masked (BRAND_/MODEL_<sha6>); Aurora Motors and the residual kept"]
    out = Path(ARGS.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(head + LINES) + "\n", encoding="utf-8")
    print("\n".join(head))
    print("\n".join(l for l in LINES if l.startswith("FAIL")))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
