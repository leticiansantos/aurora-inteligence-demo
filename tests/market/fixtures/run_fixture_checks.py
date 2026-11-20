#!/usr/bin/env python3
"""Prove the SQL violation checks in tests/market/sql work, with no workspace objects.

Every `__T__market_X` reference is rewritten to an inline CTE built from VALUES
(read-only SELECT). The CLEAN dataset must give 0 rows for every check; each
MUTATED dataset seeds one defect and must give >= 1 row (and contain the
expected violation label in the output).

Usage: python3 run_fixture_checks.py [--profile classic-stable-new] [--workers 4]
"""
import argparse
import copy
import csv
import datetime as dt
import io
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"

SHARE_COLS = [("ref_month", "DATE"), ("segment", "STRING"), ("brand", "STRING"), ("units", "BIGINT"),
              ("segment_total_units", "BIGINT"), ("share", "DOUBLE"), ("rank", "INT"),
              ("is_synthetic", "BOOLEAN"), ("is_residual", "BOOLEAN")]
SCHEMA = {
    "download_manifest": [("source_url", "STRING"), ("url_month", "DATE"), ("file_path", "STRING"),
                          ("bytes", "BIGINT"), ("sha256", "STRING"), ("status", "STRING"),
                          ("duplicate_of", "STRING"), ("http_status", "INT"), ("origin", "STRING"),
                          ("source_last_modified", "TIMESTAMP"), ("attempted_at", "TIMESTAMP"),
                          ("downloaded_at", "TIMESTAMP")],
    "documents": [("source_path", "STRING"), ("file_name", "STRING"), ("ref_month", "DATE"),
                  ("month_source", "STRING"), ("parse_dialect", "STRING"), ("parse_status", "STRING"),
                  ("is_selected", "BOOLEAN"), ("source_last_modified", "TIMESTAMP"), ("_ingested_at", "TIMESTAMP")],
    "segment_totals": [("ref_month", "DATE"), ("segment", "STRING"), ("units", "INT"),
                       ("brand_table_found", "BOOLEAN"), ("model_table_found", "BOOLEAN"),
                       ("source_file", "STRING"), ("parse_dialect", "STRING")],
    "registrations_brand": [("ref_month", "DATE"), ("segment", "STRING"), ("brand", "STRING"), ("units", "INT"),
                            ("rank", "INT"), ("source_file", "STRING"), ("page_id", "INT"), ("parse_dialect", "STRING")],
    "registrations_model": [("ref_month", "DATE"), ("segment", "STRING"), ("brand", "STRING"), ("brand_raw", "STRING"),
                            ("brand_matched", "BOOLEAN"), ("model", "STRING"), ("units", "INT"), ("rank", "INT"),
                            ("source_file", "STRING"), ("page_id", "INT"), ("parse_dialect", "STRING")],
    "synthetic_registrations": [("ref_month", "DATE"), ("segment", "STRING"), ("brand", "STRING"),
                                ("model", "STRING"), ("units", "INT"), ("target_share", "DOUBLE"),
                                ("is_synthetic", "BOOLEAN"), ("generator_version", "STRING"), ("seed", "INT")],
    "brand_monthly": [("ref_month", "DATE"), ("segment", "STRING"), ("brand", "STRING"), ("units", "INT"),
                      ("rank", "INT"), ("is_synthetic", "BOOLEAN"), ("is_residual", "BOOLEAN")],
    "share_real": SHARE_COLS,
    "share_with_aurora": SHARE_COLS,
}

AUTO, CL = "automoveis", "comerciais_leves"
AURORA = "AURORA MOTORS"
TOTAL = {AUTO: 1000, CL: 200}
BA, BB, BC = "MARCA A", "MARCA B", "MARCA C"
BRANDS = {AUTO: [(BA, 500), (BB, 300), (BC, 190)],   # residual 10 = 1%
          CL: [(BA, 100), (BB, 60), (BC, 38)]}       # residual 2 = 1%
AURORA_MODELS = [("IPE", 15), ("JATOBA", 12), ("AROEIRA", 9)]  # 36 = round(.035 * 1000 / .965)
AURORA_SHARE = 0.035
AURORA_UNITS = sum(u for _, u in AURORA_MODELS)
RESIDUAL = "OUTRAS (NAO PUBLICADAS)"
ZERO_MONTH = dt.date(2019, 1, 1)       # Aurora launch month: 3 rows with 0 units
NO_BRAND_MONTH = dt.date(2004, 1, 1)   # known no-brand-table month (default allow-list)
TS = dt.datetime(2026, 1, 1, 0, 0, 0)


def months(start, end):
    y, m = start
    while (y, m) <= end:
        yield dt.date(y, m, 1)
        m += 1
        if m == 13:
            y, m = y + 1, 1


# compact months used by every check except 01; 01 uses the contiguous 2003-01..2022-03 range
COMPACT = (list(months((2003, 1), (2003, 3))) + [NO_BRAND_MONTH] + list(months((2019, 1), (2019, 2)))
           + list(months((2022, 1), (2022, 2))) + [dt.date(2023, 1, 1)])
FULL = list(months((2003, 1), (2022, 3)))


def share_row(d, seg, brand, units, den, rank, syn=False, res=False):
    return dict(ref_month=d, segment=seg, brand=brand, units=units, segment_total_units=den,
                share=units / den, rank=rank, is_synthetic=syn, is_residual=res)


def clean(month_list=COMPACT):
    t = {k: [] for k in SCHEMA}
    for d in month_list:
        ym = f"{d:%Y-%m}"
        url = f"https://example.org/{ym}.pdf"
        t["download_manifest"].append(dict(
            source_url=url, url_month=d, file_path=f"/v/{ym}.pdf", bytes=50000, sha256=f"sha{d:%Y%m}",
            status="downloaded", duplicate_of=None, http_status=200, origin="seed", source_last_modified=TS,
            attempted_at=TS, downloaded_at=TS))
        t["documents"].append(dict(
            source_path=f"/v/{ym}.pdf", file_name=f"{ym}.pdf", ref_month=d, month_source="p6_header",
            parse_dialect="d1", parse_status="ok", is_selected=True, source_last_modified=TS, _ingested_at=TS))
        nobrand = d == NO_BRAND_MONTH
        for seg in (AUTO, CL):
            tot = TOTAL[seg]
            t["segment_totals"].append(dict(ref_month=d, segment=seg, units=tot, brand_table_found=not nobrand,
                                            model_table_found=not nobrand, source_file=f"{ym}.pdf", parse_dialect="d1"))
            aur_active = seg == AUTO and d >= dt.date(2019, 1, 1)
            zero = d == ZERO_MONTH
            syn = AURORA_UNITS if (aur_active and not zero) else 0
            den = tot + syn
            real_sum = 0
            for k, (b, u) in ([] if nobrand else enumerate(BRANDS[seg])):
                real_sum += u
                t["registrations_brand"].append(dict(ref_month=d, segment=seg, brand=b, units=u, rank=k + 1,
                                                     source_file=f"{ym}.pdf", page_id=1, parse_dialect="d1"))
                t["registrations_model"].append(dict(ref_month=d, segment=seg, brand=b, brand_raw=b, brand_matched=True,
                                                     model=f"MODELO {b[-1]}1", units=u // 2, rank=k + 1,
                                                     source_file=f"{ym}.pdf", page_id=2, parse_dialect="d1"))
                t["brand_monthly"].append(dict(ref_month=d, segment=seg, brand=b, units=u, rank=k + 1, is_synthetic=False, is_residual=False))
                t["share_real"].append(share_row(d, seg, b, u, tot, k + 1))
                t["share_with_aurora"].append(share_row(d, seg, b, u, den, k + 1))
            res = tot - real_sum   # 100% of the total in the no-brand month
            t["brand_monthly"].append(dict(ref_month=d, segment=seg, brand=RESIDUAL, units=res, rank=None, is_synthetic=False, is_residual=True))
            t["share_real"].append(share_row(d, seg, RESIDUAL, res, tot, None, res=True))
            t["share_with_aurora"].append(share_row(d, seg, RESIDUAL, res, den, None, res=True))
            if aur_active:
                for mdl, u in AURORA_MODELS:
                    t["synthetic_registrations"].append(dict(ref_month=d, segment=seg, brand=AURORA, model=mdl,
                                                             units=0 if zero else u,
                                                             target_share=0.0 if zero else AURORA_SHARE, is_synthetic=True,
                                                             generator_version="v1", seed=42))
                t["brand_monthly"].append(dict(ref_month=d, segment=seg, brand=AURORA, units=syn, rank=None, is_synthetic=True, is_residual=False))
                t["share_with_aurora"].append(share_row(d, seg, AURORA, syn, den, 4, syn=True))
    # legitimate non-downloaded manifest rows: a not_found probe and a duplicate of the 2003-01 file
    t["download_manifest"].append(dict(
        source_url="https://example.org/2003-04-alt.pdf", url_month=dt.date(2003, 4, 1), file_path=None, bytes=None,
        sha256=None, status="not_found", duplicate_of=None, http_status=404, origin="discovery",
        source_last_modified=None, attempted_at=TS, downloaded_at=None))
    first = t["download_manifest"][0]
    t["download_manifest"].append(dict(
        source_url="https://example.org/2003-01-copy.pdf", url_month=first["url_month"], file_path=None, bytes=None,
        sha256=first["sha256"], status="duplicate", duplicate_of=first["source_url"], http_status=200, origin="discovery",
        source_last_modified=TS, attempted_at=TS, downloaded_at=None))
    # a second, non-selected document for 2003-03 (re-download of the same month) is legitimate
    d3 = dt.date(2003, 3, 1)
    if d3 in month_list:
        t["documents"].append(dict(source_path="/v/2003-03-alt.pdf", file_name="2003-03-alt.pdf", ref_month=d3,
                                   month_source="title", parse_dialect="d1", parse_status="ok", is_selected=False,
                                   source_last_modified=TS, _ingested_at=TS))
    return t


def lit(v, typ):
    if v is None:
        return f"CAST(NULL AS {typ})"
    if typ == "DATE":
        return f"DATE'{v:%Y-%m-%d}'"
    if typ == "TIMESTAMP":
        return f"TIMESTAMP'{v:%Y-%m-%d %H:%M:%S}'"
    if typ == "STRING":
        return "'" + v.replace("'", "''") + "'"
    if typ == "BOOLEAN":
        return "true" if v else "false"
    if typ in ("BIGINT", "INT"):
        return f"CAST({int(v)} AS {typ})"
    if typ == "DOUBLE":
        return f"CAST({v!r} AS DOUBLE)"
    raise ValueError(typ)


def cte(name, rows):
    cols = SCHEMA[name]
    colnames = ", ".join(c for c, _ in cols)
    if not rows:  # empty typed relation
        sel = ", ".join(f"CAST(NULL AS {ty}) AS {c}" for c, ty in cols)
        return f"market_{name} AS (SELECT {sel} WHERE false)"
    vals = ",\n".join("(" + ", ".join(lit(r[c], ty) for c, ty in cols) + ")" for r in rows)
    return f"market_{name} AS (SELECT * FROM VALUES\n{vals}\nAS t({colnames}))"


def build_sql(sql, tables, params=None):
    # drop only the leading comment header; inline comments are kept
    lines = sql.splitlines()
    while lines and lines[0].lstrip().startswith("--"):
        lines.pop(0)
    body = "\n".join(lines).strip()
    used = sorted(set(re.findall(r"__T__market_(\w+)", body)))
    body = re.sub(r"__T__market_(\w+)", r"market_\1", body)
    for k, v in {"__KNOWN_MISSING__": "", "__KNOWN_NO_BRAND__": "2004-01-01", "__KNOWN_NO_MODEL__": "2004-01-01", **(params or {})}.items():
        body = body.replace(k, v)
    ctes = ",\n".join(cte(n, tables[n]) for n in used)
    if re.match(r"WITH\b", body, re.I):
        return "WITH " + ctes + ",\n" + body[4:].lstrip()
    return "WITH " + ctes + "\n" + body


def run_sql(sql, profile):
    p = subprocess.run(["databricks", "experimental", "aitools", "tools", "query", "--profile", profile,
                        "--output", "csv", sql], capture_output=True, text=True)
    if p.returncode != 0:
        return None, (p.stderr + p.stdout).strip()
    rows = list(csv.reader(io.StringIO(p.stdout)))
    return rows, p.stdout


# ---- mutations -------------------------------------------------------------
D = dt.date
M = D(2003, 2, 1)       # a month present in the compact dataset
M01 = D(2010, 5, 1)     # a month present in the full (01-only) dataset
Z = D(2019, 1, 1)       # first Aurora month: legitimately 3 rows with units=0, target_share=0
L = D(2019, 2, 1)       # a regular Aurora month (36 units, 3.5%)
Y22 = D(2022, 1, 1)     # month where the 3% lower band applies


def sel(rows, **kw):
    return [r for r in rows if all(r[k] == v for k, v in kw.items())]


def drop(t, name, **kw):
    t[name] = [r for r in t[name] if r not in sel(t[name], **kw)]


def set_aurora(t, d, units):
    """Change Aurora units in one month consistently across synthetic table and with-Aurora view."""
    for r in sel(t["synthetic_registrations"], ref_month=d):
        if r["model"] == "IPE":
            r["units"] = units - 21
    den = TOTAL[AUTO] + units
    for r in sel(t["share_with_aurora"], ref_month=d, segment=AUTO):
        r["segment_total_units"] = den
        if r["brand"] == AURORA:
            r["units"] = units
        r["share"] = r["units"] / den


def set_aurora_total(t, d, total, a):
    """Month d, automoveis: published total = `total` units, Aurora = `a` units (views and silver kept consistent)."""
    first_ = lambda name, **kw: sel(t[name], ref_month=d, segment=AUTO, **kw)[0]
    first_("segment_totals")["units"] = total
    first_("share_real", brand=BA)["units"] += total - TOTAL[AUTO]
    for r in sel(t["share_real"], ref_month=d, segment=AUTO): r["segment_total_units"] = total
    first_("brand_monthly", brand=BA)["units"] += total - TOTAL[AUTO]
    first_("share_with_aurora", brand=BA)["units"] += total - TOTAL[AUTO]
    for r in sel(t["share_with_aurora"], ref_month=d, segment=AUTO): r["segment_total_units"] = total + a
    first_("share_with_aurora", brand=AURORA)["units"] = a
    first_("brand_monthly", brand=AURORA)["units"] = a
    first_("synthetic_registrations", model="IPE")["units"] = a - 21


def mutations():
    out = []  # (check_prefix, case, expected_label or None for "0 rows", fn) ; fn may return params dict

    def add(prefix, case, label):
        def deco(fn):
            out.append((prefix, case, label, fn))
            return fn
        return deco

    def first(t, name, **kw): return sel(t[name], **kw)[0]

    # 01 coverage (full contiguous dataset 2003-01..2022-03)
    @add("01", "month_absent", "month_absent")
    def _(t): drop(t, "segment_totals", ref_month=M01)

    @add("01", "month_absent_allow_listed", None)
    def _(t):
        drop(t, "segment_totals", ref_month=M01)
        return {"__KNOWN_MISSING__": "2010-05-01"}

    @add("01", "allow_listed_month_present", "allow_listed_month_present")
    def _(t): return {"__KNOWN_MISSING__": "2010-05-01"}

    @add("01", "only_one_segment_absent_is_not_a_gap", None)
    def _(t): drop(t, "segment_totals", ref_month=M01, segment=CL)  # documents: 01 only checks month presence

    # 02 manifest
    @add("02", "duplicate_source_url", "duplicate_source_url")
    def _(t):
        r = copy.deepcopy(t["download_manifest"][0]); r["sha256"] = "other"
        t["download_manifest"].append(r)

    @add("02", "same_content_downloaded_twice", "same_content_downloaded_twice")
    def _(t): first(t, "download_manifest", url_month=D(2003, 3, 1), status="downloaded")["sha256"] = "sha200301"

    @add("02", "downloaded_tiny_bytes", "downloaded_without_file")
    def _(t): t["download_manifest"][0]["bytes"] = 5

    @add("02", "downloaded_null_sha", "downloaded_without_file")
    def _(t): t["download_manifest"][0]["sha256"] = None

    @add("02", "downloaded_null_file_path", "downloaded_without_file")
    def _(t): t["download_manifest"][0]["file_path"] = None

    @add("02", "duplicate_without_original", "duplicate_without_original")
    def _(t): first(t, "download_manifest", status="duplicate")["duplicate_of"] = "https://example.org/nope.pdf"

    @add("02", "duplicate_of_null", "duplicate_without_original")
    def _(t): first(t, "download_manifest", status="duplicate")["duplicate_of"] = None

    @add("02", "duplicate_original_not_downloaded", "duplicate_without_original")
    def _(t): first(t, "download_manifest", url_month=D(2003, 1, 1), status="downloaded")["status"] = "failed"

    @add("02", "duplicate_sha_differs_from_original", "duplicate_without_original")
    def _(t): first(t, "download_manifest", status="duplicate")["sha256"] = "different"

    @add("02", "unknown_status", "unknown_status_or_origin")
    def _(t): t["download_manifest"][0]["status"] = "weird"

    @add("02", "old_status_missing_is_unknown", "unknown_status_or_origin")
    def _(t): t["download_manifest"][0]["status"] = "missing"

    @add("02", "null_status", "unknown_status_or_origin")
    def _(t): t["download_manifest"][0]["status"] = None

    @add("02", "bad_origin", "unknown_status_or_origin")
    def _(t): t["download_manifest"][0]["origin"] = "crawler"

    @add("02", "null_origin", "unknown_status_or_origin")
    def _(t): t["download_manifest"][0]["origin"] = None

    # 03 segment totals
    @add("03", "duplicate_key", "duplicate_key")
    def _(t): t["segment_totals"].append(copy.deepcopy(first(t, "segment_totals", ref_month=M, segment=AUTO)))

    @add("03", "missing_segment", "missing_month_segment")
    def _(t): drop(t, "segment_totals", ref_month=M, segment=CL)

    @add("03", "zero_units", "bad_value")
    def _(t): first(t, "segment_totals", ref_month=M, segment=CL)["units"] = 0

    @add("03", "unknown_segment", "bad_value")
    def _(t): t["segment_totals"].append(dict(first(t, "segment_totals", ref_month=M, segment=CL), segment="motos"))

    @add("03", "not_first_of_month", "bad_value")
    def _(t): t["segment_totals"].append(dict(first(t, "segment_totals", ref_month=M, segment=AUTO), ref_month=D(2003, 2, 15)))

    @add("03", "null_brand_table_found", "bad_value")
    def _(t): first(t, "segment_totals", ref_month=M, segment=CL)["brand_table_found"] = None

    @add("03", "null_model_table_found", "bad_value")
    def _(t): first(t, "segment_totals", ref_month=M, segment=CL)["model_table_found"] = None

    @add("03", "model_table_missing_not_allow_listed", "model_table_missing_not_allow_listed")
    def _(t):
        first(t, "segment_totals", ref_month=M, segment=CL)["model_table_found"] = False
        t["registrations_model"] = [r for r in t["registrations_model"] if not (r["ref_month"] == M and r["segment"] == CL)]

    @add("03", "model_table_missing_allow_listed", None)
    def _(t):
        first(t, "segment_totals", ref_month=M, segment=CL)["model_table_found"] = False
        t["registrations_model"] = [r for r in t["registrations_model"] if not (r["ref_month"] == M and r["segment"] == CL)]
        return {"__KNOWN_NO_MODEL__": f"{M:%Y-%m-%d},2004-01-01"}

    @add("03", "null_source_file", "bad_value")
    def _(t): first(t, "segment_totals", ref_month=M, segment=CL)["source_file"] = None

    @add("03", "model_flag_true_but_no_model_rows", "model_flag_inconsistent")
    def _(t): drop(t, "registrations_model", ref_month=M, segment=CL)

    @add("03", "model_flag_false_but_model_rows", "model_flag_inconsistent")
    def _(t): first(t, "segment_totals", ref_month=M, segment=AUTO)["model_table_found"] = False

    @add("03", "model_flag_true_in_no_table_month", "model_flag_inconsistent")
    def _(t): first(t, "segment_totals", ref_month=NO_BRAND_MONTH, segment=CL)["model_table_found"] = True

    # 04 brand silver
    @add("04", "duplicate_key", "duplicate_key")
    def _(t): t["registrations_brand"].append(copy.deepcopy(t["registrations_brand"][0]))

    @add("04", "negative_units", "null_or_negative")
    def _(t): t["registrations_brand"][0]["units"] = -1

    @add("04", "blank_brand", "null_or_negative")
    def _(t): t["registrations_brand"][0]["brand"] = "  "

    @add("04", "null_rank", "null_or_negative")
    def _(t): t["registrations_brand"][0]["rank"] = None

    @add("04", "rank_zero", "null_or_negative")
    def _(t): t["registrations_brand"][0]["rank"] = 0

    @add("04", "rank_inverted", "rank_order_or_start")
    def _(t):
        a = first(t, "registrations_brand", ref_month=M, segment=AUTO, brand=BA)
        b = first(t, "registrations_brand", ref_month=M, segment=AUTO, brand=BB)
        a["rank"], b["rank"] = b["rank"], a["rank"]

    @add("04", "no_rank_1", "no_rank_1")
    def _(t):
        for r in sel(t["registrations_brand"], ref_month=M, segment=CL): r["rank"] += 1

    @add("04", "published_tie_is_ok", None)
    def _(t):
        a = first(t, "registrations_brand", ref_month=M, segment=CL, brand=BB)
        b = first(t, "registrations_brand", ref_month=M, segment=CL, brand=BC)
        b["units"] = a["units"]; a["units"] = b["units"]
        b["rank"] = a["rank"]

    @add("04", "aurora_in_silver", "synthetic_in_real")
    def _(t): t["registrations_brand"].append(dict(t["registrations_brand"][0], ref_month=L, brand=AURORA, rank=9))

    @add("04", "aurora_mixed_case_in_silver", "synthetic_in_real")
    def _(t): t["registrations_brand"].append(dict(t["registrations_brand"][0], ref_month=L, brand="Aurora Motors", rank=9))

    @add("04", "residual_name_in_silver", "synthetic_in_real")
    def _(t): t["registrations_brand"].append(dict(t["registrations_brand"][0], brand=RESIDUAL, rank=9))

    @add("04", "unknown_segment", "unknown_segment")
    def _(t): t["registrations_brand"].append(dict(t["registrations_brand"][0], segment="motos", brand="X"))

    @add("04", "month_without_totals", "month_without_totals")
    def _(t): t["registrations_brand"].append(dict(t["registrations_brand"][0], ref_month=D(2003, 5, 1)))

    # 05 model silver
    @add("05", "duplicate_key", "duplicate_key")
    def _(t): t["registrations_model"].append(copy.deepcopy(t["registrations_model"][0]))

    @add("05", "rank_zero", "null_or_negative")
    def _(t): t["registrations_model"][0]["rank"] = 0

    @add("05", "null_model", "null_or_negative")
    def _(t): t["registrations_model"][0]["model"] = None

    @add("05", "brand_matched_null", "null_or_negative")
    def _(t): t["registrations_model"][0]["brand_matched"] = None

    @add("05", "brand_unmatched_is_allowed", None)
    def _(t): t["registrations_model"][0].update(brand_matched=False, brand_raw="MARCA A (RAW)")

    @add("05", "model_starting_with_brand_is_allowed", None)
    def _(t):
        r = t["registrations_model"][0]; r["model"] = r["brand"] + "/" + r["model"]

    @add("05", "aurora_in_model_silver", "synthetic_in_real")
    def _(t): t["registrations_model"].append(dict(t["registrations_model"][0], ref_month=L, brand=AURORA, model="IPE", rank=9))

    @add("05", "top_n_exceeds_total", "top_n_exceeds_total")
    def _(t): first(t, "registrations_model", ref_month=M, segment=CL, brand=BA)["units"] = 500

    # 06 brand residual / known-no-brand
    @add("06", "residual_over_3pct", "residual_over_3pct")
    def _(t): first(t, "registrations_brand", ref_month=M, segment=AUTO, brand=BC)["units"] = 100  # residual 10%

    @add("06", "brands_exceed_total", "brands_exceed_total")
    def _(t): first(t, "registrations_brand", ref_month=M, segment=AUTO, brand=BC)["units"] = 400

    @add("06", "flag_true_but_no_brand_rows", "flag_true_but_no_brand_rows")
    def _(t): drop(t, "registrations_brand", ref_month=M, segment=CL)

    @add("06", "null_flag", "null_flag")
    def _(t): first(t, "segment_totals", ref_month=M, segment=CL)["brand_table_found"] = None

    def no_brand(t):
        drop(t, "registrations_brand", ref_month=M)
        for r in sel(t["segment_totals"], ref_month=M): r["brand_table_found"] = False

    @add("06", "no_brand_table_not_allow_listed", "no_brand_table_not_allow_listed")
    def _(t): no_brand(t)

    @add("06", "no_brand_table_allow_listed", None)
    def _(t):
        no_brand(t)
        return {"__KNOWN_NO_BRAND__": "2003-02-01,2004-01-01"}

    @add("06", "default_no_brand_month_not_allow_listed", "no_brand_table_not_allow_listed")
    def _(t): return {"__KNOWN_NO_BRAND__": ""}

    @add("06", "no_brand_month_with_flag_true", "flag_true_but_no_brand_rows")
    def _(t):
        for r in sel(t["segment_totals"], ref_month=NO_BRAND_MONTH): r["brand_table_found"] = True

    @add("06", "flag_false_but_brand_rows", "flag_false_but_brand_rows")
    def _(t):
        first(t, "segment_totals", ref_month=M, segment=CL)["brand_table_found"] = False
        return {"__KNOWN_NO_BRAND__": "2003-02-01,2004-01-01"}

    @add("06", "flag_false_brand_rows_not_listed", "no_brand_table_not_allow_listed")
    def _(t): first(t, "segment_totals", ref_month=M, segment=CL)["brand_table_found"] = False

    # 07 gold
    @add("07", "gold_sum_ne_total", "real_gold_ne_total")
    def _(t): first(t, "brand_monthly", ref_month=M, segment=AUTO, brand=BA)["units"] = 499

    @add("07", "gold_month_missing", "real_gold_ne_total")
    def _(t): drop(t, "brand_monthly", ref_month=M, segment=CL)

    @add("07", "no_brand_month_residual_not_100pct", "real_gold_ne_total")
    def _(t): first(t, "brand_monthly", ref_month=NO_BRAND_MONTH, segment=AUTO, is_residual=True)["units"] = 900

    @add("07", "synthetic_residual", "bad_residual_row")
    def _(t): first(t, "brand_monthly", ref_month=M, segment=AUTO, is_residual=True)["is_synthetic"] = True

    @add("07", "negative_residual", "bad_residual_row")
    def _(t):  # keep sum == total so only the residual rule fires
        first(t, "brand_monthly", ref_month=M, segment=AUTO, brand=BA)["units"] += 20
        first(t, "brand_monthly", ref_month=M, segment=AUTO, is_residual=True)["units"] = -10

    @add("07", "residual_with_rank", "bad_residual_row")
    def _(t): first(t, "brand_monthly", ref_month=M, segment=AUTO, is_residual=True)["rank"] = 4

    @add("07", "residual_wrong_name", "bad_residual_row")
    def _(t): first(t, "brand_monthly", ref_month=M, segment=AUTO, is_residual=True)["brand"] = "OUTROS"

    @add("07", "aurora_with_rank", "bad_flags_or_rank")
    def _(t): first(t, "brand_monthly", ref_month=L, segment=AUTO, brand=AURORA)["rank"] = 4

    @add("07", "real_row_without_rank", "bad_flags_or_rank")
    def _(t): first(t, "brand_monthly", ref_month=M, segment=AUTO, brand=BA)["rank"] = None

    @add("07", "synthetic_row_not_aurora", "bad_flags_or_rank")
    def _(t): first(t, "brand_monthly", ref_month=L, segment=AUTO, brand=AURORA)["brand"] = "OTHER"

    @add("07", "aurora_name_not_flagged_synthetic", "bad_flags_or_rank")
    def _(t): first(t, "brand_monthly", ref_month=L, segment=AUTO, brand=AURORA)["is_synthetic"] = False

    @add("07", "null_is_synthetic", "bad_flags_or_rank")
    def _(t): first(t, "brand_monthly", ref_month=M, segment=AUTO, brand=BA)["is_synthetic"] = None

    @add("07", "aurora_gold_ne_silver", "aurora_gold_ne_silver")
    def _(t): first(t, "brand_monthly", ref_month=L, segment=AUTO, brand=AURORA)["units"] = 30

    @add("07", "aurora_gold_row_missing", "aurora_gold_ne_silver")
    def _(t): drop(t, "brand_monthly", ref_month=L, segment=AUTO, brand=AURORA)

    @add("07", "aurora_gold_without_silver", "aurora_gold_ne_silver")
    def _(t): drop(t, "synthetic_registrations", ref_month=L)

    @add("07", "two_residual_rows", "residual_count_ne_1")
    def _(t): t["brand_monthly"].append(dict(ref_month=M, segment=AUTO, brand="OUTRAS 2", units=0, rank=None, is_synthetic=False, is_residual=True))

    @add("07", "no_residual_row", "residual_count_ne_1")
    def _(t): first(t, "brand_monthly", ref_month=M, segment=AUTO, is_residual=True)["is_residual"] = False

    @add("07", "duplicate_key", "duplicate_key")
    def _(t): t["brand_monthly"].append(dict(ref_month=M, segment=AUTO, brand=BA, units=0, rank=1, is_synthetic=False, is_residual=False))

    # 08 synthetic rules
    @add("08", "wrong_brand", "rule_violation")
    def _(t): t["synthetic_registrations"][0]["brand"] = BA

    @add("08", "in_comerciais_leves", "rule_violation")
    def _(t): t["synthetic_registrations"].append(dict(t["synthetic_registrations"][0], segment=CL))

    @add("08", "before_launch", "rule_violation")
    def _(t): t["synthetic_registrations"].append(dict(t["synthetic_registrations"][0], ref_month=D(2018, 12, 1)))

    @add("08", "bad_model", "rule_violation")
    def _(t): t["synthetic_registrations"][0]["model"] = "XYZ"

    @add("08", "not_flagged", "rule_violation")
    def _(t): t["synthetic_registrations"][0]["is_synthetic"] = False

    @add("08", "negative_units", "rule_violation")
    def _(t): t["synthetic_registrations"][0]["units"] = -3

    @add("08", "null_target_share", "rule_violation")
    def _(t): t["synthetic_registrations"][0]["target_share"] = None

    @add("08", "null_seed", "rule_violation")
    def _(t): t["synthetic_registrations"][0]["seed"] = None

    @add("08", "duplicate_key", "duplicate_key")
    def _(t): t["synthetic_registrations"].append(copy.deepcopy(t["synthetic_registrations"][0]))

    @add("08", "missing_after_launch", "no_synthetic_after_launch")
    def _(t): drop(t, "synthetic_registrations", ref_month=D(2019, 2, 1))

    @add("08", "synthetic_month_without_totals", "synthetic_month_without_totals")
    def _(t): t["synthetic_registrations"].append(dict(t["synthetic_registrations"][0], ref_month=D(2019, 3, 1), model="JATOBA"))

    @add("08", "volume_ne_share_formula", "volume_ne_share_formula")
    def _(t): first(t, "synthetic_registrations", ref_month=L, model="IPE")["units"] += 10

    @add("08", "volume_within_rounding_tolerance", None)
    def _(t): first(t, "synthetic_registrations", ref_month=L, model="IPE")["units"] += 2

    @add("08", "target_share_differs_across_models", "volume_ne_share_formula")
    def _(t): first(t, "synthetic_registrations", ref_month=L, model="IPE")["target_share"] = AURORA_SHARE + 0.0001

    @add("08", "zero_unit_month_with_nonzero_target_share", "volume_ne_share_formula")
    def _(t):
        for r in sel(t["synthetic_registrations"], ref_month=Z): r["target_share"] = AURORA_SHARE

    # 09 views isolation
    @add("09", "aurora_in_real_view", "synthetic_in_real_view")
    def _(t): t["share_real"].append(share_row(L, AUTO, AURORA, 36, 1000, 4, syn=True))

    @add("09", "aurora_unflagged_in_real_view", "synthetic_in_real_view")
    def _(t): t["share_real"].append(share_row(L, AUTO, "Aurora Motors", 36, 1000, 4))

    @add("09", "real_view_units_ne_total", "real_view_ne_total")
    def _(t): first(t, "share_real", ref_month=M, segment=AUTO, brand=BA)["units"] = 400

    @add("09", "real_view_denominator_wrong", "real_view_ne_total")
    def _(t): first(t, "share_real", ref_month=M, segment=AUTO, brand=BA)["segment_total_units"] = 999

    @add("09", "with_aurora_units_ne_real_plus_syn", "with_aurora_ne_real_plus_synthetic")
    def _(t): first(t, "share_with_aurora", ref_month=L, segment=AUTO, brand=AURORA)["units"] = 20

    @add("09", "with_aurora_denominator_excludes_aurora", "with_aurora_ne_real_plus_synthetic")
    def _(t):
        for r in sel(t["share_with_aurora"], ref_month=L, segment=AUTO): r["segment_total_units"] = 1000

    @add("09", "aurora_in_comerciais_leves", "with_aurora_ne_real_plus_synthetic")
    def _(t): t["share_with_aurora"].append(share_row(L, CL, AURORA, 5, 205, 4, syn=True))

    @add("09", "aurora_share_over_4pct_2019", "aurora_share_out_of_band")
    def _(t): set_aurora(t, L, 100)   # 100/1100 = 9.1%

    @add("09", "aurora_share_2pct_2022", "aurora_share_out_of_band")
    def _(t): set_aurora(t, Y22, 20)  # 20/1020 = 1.96% < 3%

    @add("09", "aurora_share_low_2019_is_ok", None)
    def _(t): set_aurora(t, L, 20)    # 2% before 2022 is inside [0,4%]

    @add("09", "aurora_share_4005_in_2023_within_tolerance", None)
    def _(t): set_aurora_total(t, D(2023, 1, 1), 100000, 4172)   # 4.0049%

    @add("09", "aurora_share_402_in_2023_over_tolerance", "aurora_share_out_of_band")
    def _(t): set_aurora_total(t, D(2023, 1, 1), 100000, 4188)   # 4.0197%

    @add("09", "aurora_share_2995_in_2022_within_tolerance", None)
    def _(t): set_aurora_total(t, Y22, 100000, 3087)             # 2.9948%

    @add("09", "aurora_share_2990_in_2022_under_tolerance", "aurora_share_out_of_band")
    def _(t): set_aurora_total(t, Y22, 100000, 3080)             # 2.9880%

    # 10 share sanity
    def share_rows(t, view, d, seg): return {r["brand"]: r for r in sel(t[view], ref_month=d, segment=seg)}

    @add("10", "real_share_sum_ne_1", "share_sum_ne_1")
    def _(t): first(t, "share_real", ref_month=M, segment=AUTO, brand=BA)["share"] = 0.4

    @add("10", "with_aurora_share_sum_ne_1", "share_sum_ne_1")
    def _(t): first(t, "share_with_aurora", ref_month=L, segment=AUTO, brand=BA)["share"] = 0.3

    @add("10", "negative_share", "share_ne_units_over_total")
    def _(t):
        r = share_rows(t, "share_real", M, AUTO)  # .81 / -.01 / .19 / .01 sums to 1 but one share < 0
        r[BA]["share"], r[BB]["share"] = 0.81, -0.01

    @add("10", "share_ne_units_over_total", "share_ne_units_over_total")
    def _(t):  # sum stays 1, but shares no longer = units / segment_total_units
        r = share_rows(t, "share_real", M, AUTO)
        r[BA]["share"] += 0.01; r[BB]["share"] -= 0.01

    @add("10", "with_aurora_share_uses_wrong_denominator", "share_ne_units_over_total")
    def _(t):
        for r in sel(t["share_with_aurora"], ref_month=L, segment=AUTO): r["share"] = r["units"] / 1000

    @add("10", "residual_with_rank", "bad_residual_row")
    def _(t): share_rows(t, "share_real", M, AUTO)[RESIDUAL]["rank"] = 5

    @add("10", "residual_synthetic", "bad_residual_row")
    def _(t): share_rows(t, "share_with_aurora", M, AUTO)[RESIDUAL]["is_synthetic"] = True

    @add("10", "non_residual_null_rank", "ranked_row_without_rank")
    def _(t): share_rows(t, "share_real", M, AUTO)[BA]["rank"] = None

    @add("10", "non_residual_rank_zero", "ranked_row_without_rank")
    def _(t): share_rows(t, "share_with_aurora", M, AUTO)[BA]["rank"] = 0

    @add("10", "view_rank_not_by_units", "rank_not_dense_by_units")
    def _(t):
        r = share_rows(t, "share_real", M, AUTO); r[BA]["rank"], r[BB]["rank"] = r[BB]["rank"], r[BA]["rank"]

    @add("10", "view_rank_gap", "dense_rank_gap")
    def _(t):
        r = share_rows(t, "share_real", M, AUTO); r[BC]["rank"] += 1

    # 11 documents
    @add("11", "parse_status_error", "not_parsed_ok")
    def _(t): first(t, "documents", ref_month=M)["parse_status"] = "error"

    @add("11", "unselected_no_month_document_is_ok", None)
    def _(t): t["documents"].append(dict(t["documents"][0], file_name="x.pdf", source_path="/v/x.pdf", ref_month=None,
                                         parse_status="no_month", month_source=None, is_selected=False))

    @add("11", "selected_no_month_document", "selected_not_parsed_ok")
    def _(t): t["documents"].append(dict(t["documents"][0], file_name="x.pdf", source_path="/v/x.pdf", ref_month=None,
                                         parse_status="no_month", month_source=None, is_selected=True))

    @add("11", "null_is_selected", "selected_not_parsed_ok")
    def _(t): first(t, "documents", ref_month=M)["is_selected"] = None

    @add("11", "null_parse_status", "not_parsed_ok")
    def _(t): first(t, "documents", ref_month=M)["parse_status"] = None

    @add("11", "two_selected_docs_for_month", "selected_count_ne_1")
    def _(t): first(t, "documents", file_name="2003-03-alt.pdf")["is_selected"] = True

    @add("11", "no_selected_doc_for_month", "selected_count_ne_1")
    def _(t): first(t, "documents", ref_month=M)["is_selected"] = False

    @add("11", "totals_not_from_selected_file", "totals_not_from_selected_file")
    def _(t): first(t, "segment_totals", ref_month=M, segment=AUTO)["source_file"] = "other.pdf"

    @add("11", "totals_from_unselected_file", "totals_not_from_selected_file")
    def _(t): first(t, "segment_totals", ref_month=D(2003, 3, 1), segment=AUTO)["source_file"] = "2003-03-alt.pdf"

    @add("11", "totals_source_file_as_source_path_is_ok", None)
    def _(t): first(t, "segment_totals", ref_month=M, segment=AUTO)["source_file"] = f"/v/{M:%Y-%m}.pdf"

    @add("11", "bad_month_source", "bad_month_source")
    def _(t): first(t, "documents", ref_month=M)["month_source"] = "guess"

    @add("11", "null_month_source", "bad_month_source")
    def _(t): first(t, "documents", ref_month=M)["month_source"] = None

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="classic-stable-new")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--only", default="", help="check prefix filter, e.g. 05")
    a = ap.parse_args()

    files = sorted(SQL_DIR.glob("*.sql"))
    base = clean()
    base_full = clean(FULL)  # 01 only: contiguous 2003-01..2022-03
    jobs = []  # (check, case, expected, label, sql)
    muts = mutations()
    for f in files:
        pre = f.name[:2]
        if a.only and pre != a.only:
            continue
        sql = f.read_text()
        b0 = base_full if pre == "01" else base
        jobs.append((f.stem, "clean", "0 rows", None, build_sql(sql, b0)))
        for p, case, label, fn in muts:
            if p == pre:
                t = copy.deepcopy(b0)
                params = fn(t)
                jobs.append((f.stem, case, ">=1 row" if label else "0 rows", label, build_sql(sql, t, params)))

    def work(j):
        return run_sql(j[4], a.profile)

    with ThreadPoolExecutor(a.workers) as ex:
        results = list(ex.map(work, jobs))

    print(f"{"check":<24}{"case":<44}{'expected':<10}{'actual':<8}result")
    bad = 0
    for (chk, case, exp, label, _), (rows, raw) in zip(jobs, results):
        if rows is None:
            n, ok, note = "ERR", False, raw.splitlines()[0][:200] if raw else ""
        else:
            n = max(len(rows) - 1, 0)
            if exp == "0 rows":
                ok = n == 0
            else:
                ok = n >= 1 and label in raw
            note = ""
            if not ok and rows:
                note = "(label %r not found)" % label if n >= 1 else ""
        bad += not ok
        print(f"{chk:<24}{case:<44}{exp:<10}{str(n):<8}{'PASS' if ok else 'FAIL'} {note}")
        if not ok and rows is None:
            print("    " + raw[:1500].replace("\n", "\n    "))
    print(f"\n{len(jobs) - bad}/{len(jobs)} cases as expected")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
