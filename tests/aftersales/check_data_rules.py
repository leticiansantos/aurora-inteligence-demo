"""Data-rule checks for every `aftersales_*` table (read-only SELECTs on the SQL warehouse).

Checks:
  1. governance: every aftersales_* table has a comment and the UC tags synthetic=true and domain=aftersales.
     Every column has a comment.
  2. no real brands: no string column contains a real brand name (whole word) taken from market_brand_monthly.
     Fictional AURORA* is allowed.
  3. no legacy data: no string column contains a part code, dealer name or image host from the old demo CSVs
     (passed with --legacy-dir; the CSVs are never copied into the repo, and only counts are written).

Usage:
  python3 -I tests/aftersales/check_data_rules.py --profile classic-stable-new --warehouse 754bcdfc4beaaaa1 \
      [--catalog classic_stable --schema auto_intelligence] [--legacy-dir <legacy-demo-dir>] \
      [--out evidence/aftersales/data-rules.txt]
Exit code 1 when any check fails.
"""
import argparse
import csv
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

KEEP_BRANDS = {"AURORA MOTORS", "AURORA", "OUTRAS (NAO PUBLICADAS)"}


def sql(args, statement: str):
    cmd = ["databricks", "experimental", "aitools", "tools", "query", "-p", args.profile,
           "-w", args.warehouse, "-o", "json", statement]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"query failed: {res.stderr.strip()[:300]}")
    out = json.loads(res.stdout or "[]")
    # single statement -> list of rows
    return out if isinstance(out, list) else out.get("rows", [])


def legacy_needles(legacy_dir: Path):
    needles = set()
    with open(legacy_dir / "pecas.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            code = (r.get("codigo_original") or "").strip()
            if len(code) >= 6:
                needles.add(code.upper())
    with open(legacy_dir / "lojas.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            name = (r.get("loja") or "").strip()
            if name:
                needles.add(name.upper())
    needles.add("CLOUDFRONT.NET")
    return sorted(needles, key=len, reverse=True)


def regex_of(words):
    # Java regex for RLIKE; whole-word match, case-insensitive via upper()
    # Spark SQL string literals drop the backslash of unknown escapes (\. -> .), so double every backslash
    # produced by re.escape, then escape single quotes for the literal.
    alts = "|".join(re.escape(w).replace("\\", "\\\\").replace("'", "\\'") for w in words)
    return f"(^|[^A-Z0-9])({alts})([^A-Z0-9]|$)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--warehouse", required=True)
    ap.add_argument("--catalog", default="classic_stable")
    ap.add_argument("--schema", default="auto_intelligence")
    ap.add_argument("--legacy-dir")
    ap.add_argument("--out", default="evidence/aftersales/data-rules.txt")
    args = ap.parse_args()
    c, s = args.catalog, args.schema
    lines, fails = [], 0

    def record(ok: bool, label: str, detail: str = ""):
        nonlocal fails
        fails += 0 if ok else 1
        lines.append(f"{'PASS' if ok else 'FAIL'}\t{label}\t{detail}")

    tables = sql(args, f"""
        SELECT table_name, table_type, comment FROM {c}.information_schema.tables
        WHERE table_schema = '{s}' AND table_name LIKE 'aftersales\\_%' ORDER BY table_name""")
    record(len(tables) > 0, "aftersales tables exist", f"n={len(tables)}")
    tags = sql(args, f"""
        SELECT table_name, tag_name, tag_value FROM {c}.information_schema.table_tags
        WHERE schema_name = '{s}' AND table_name LIKE 'aftersales\\_%'""")
    tagmap = {}
    for t in tags:
        tagmap.setdefault(t["table_name"], {})[t["tag_name"]] = t["tag_value"]
    cols = sql(args, f"""
        SELECT table_name, column_name, data_type, comment FROM {c}.information_schema.columns
        WHERE table_schema = '{s}' AND table_name LIKE 'aftersales\\_%' ORDER BY table_name, ordinal_position""")

    for t in tables:
        name = t["table_name"]
        record(bool((t.get("comment") or "").strip()), f"{name}: table comment", t.get("table_type", ""))
        tg = tagmap.get(name, {})
        record(tg.get("synthetic") == "true", f"{name}: tag synthetic=true", f"got={tg.get('synthetic')}")
        # ADR 002 D9 (792eb4d): `domain` is a governed tag key with no allowed values here, so the key is aid_domain
        record(tg.get("aid_domain") == "aftersales", f"{name}: tag aid_domain=aftersales", f"got={tg.get('aid_domain')}")
        record(tg.get("layer") in ("raw", "silver", "gold", "ml"), f"{name}: tag layer in raw/silver/gold/ml", f"got={tg.get('layer')}")
        if name.startswith("aftersales_raw_"):
            continue  # ADR D9: raw tables are exempt from column comments
        missing = [x["column_name"] for x in cols if x["table_name"] == name and not (x.get("comment") or "").strip()]
        record(not missing, f"{name}: every column commented", f"missing={missing[:10]}" if missing else "")

    brands = [r["brand"].upper() for r in sql(args, f"SELECT DISTINCT brand FROM {c}.{s}.market_brand_monthly")]
    brands = sorted({b for b in brands if b and b not in KEEP_BRANDS and not b.startswith("OUTRAS")}, key=len, reverse=True)
    needle_sets = [("real brand", brands)]
    if args.legacy_dir:
        needle_sets.append(("legacy CSV value", legacy_needles(Path(args.legacy_dir).expanduser())))

    string_cols = {}
    for x in cols:
        if x["data_type"].lower().startswith("string"):
            string_cols.setdefault(x["table_name"], []).append(x["column_name"])
    for t in tables:
        name = t["table_name"]
        sc = string_cols.get(name, [])
        if not sc:
            continue
        for label, words in needle_sets:
            rx = regex_of(words)
            exprs = ", ".join(f"count_if(upper(`{col}`) RLIKE '{rx}') AS `{col}`" for col in sc)
            row = sql(args, f"SELECT {exprs} FROM {c}.{s}.`{name}`")[0]
            hits = {k: int(v) for k, v in row.items() if v not in (None, "0", 0)}
            # counts only: never print the matched value (it may be real brand data)
            record(not hits, f"{name}: no {label} in string columns",
                   f"needles={len(words)} cols={len(sc)} hits={hits}" if hits else f"needles={len(words)} cols={len(sc)}")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    head = [f"# claim:   aftersales_* tables are commented, tagged synthetic/aid_domain/layer, free of real brands and legacy CSV data",
            f"# command: python3 -I tests/aftersales/check_data_rules.py --catalog {c} --schema {s}"
            f"{' --legacy-dir <old demo CSVs>' if args.legacy_dir else ''}",
            f"# date:    {now}  git: {sha}",
            f"# result:  {'PASS' if fails == 0 else f'FAIL ({fails})'}  checks={len(lines)}", ""]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(head + lines) + "\n", encoding="utf-8")
    print("\n".join(head + lines))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
