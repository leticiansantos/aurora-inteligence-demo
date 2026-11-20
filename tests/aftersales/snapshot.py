"""Idempotency evidence for the aftersales job (ADR 002 D8 step 7): snapshot row counts and content fingerprints
of every aftersales_* table, then diff two snapshots. Read-only SELECTs.

Fingerprint = count(*) and sum(xxhash64(all columns)) excluding run-time columns that legitimately change on a
rerun (_ingested_at, _source_file, scored_at, logged_at, run_id). Raw streaming tables must keep the same count
(Auto Loader must not re-ingest the overwritten byte-identical files).

Usage:
  python3 -I tests/aftersales/snapshot.py snap <label> --profile P --warehouse W [--catalog C --schema S]
  python3 -I tests/aftersales/snapshot.py diff <before> <after> [--out evidence/aftersales/pipeline/idempotency.txt]
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

VOLATILE = {"_ingested_at", "_source_file", "scored_at", "logged_at", "run_id", "_rescued_data", "model_version"}
MODEL = "classic_stable.auto_intelligence.aftersales_demand_forecaster"
LANDING = "dbfs:/Volumes/classic_stable/auto_intelligence/raw_landing/aftersales"
BRANCH = "projects/auto-intelligence-aftersales/branches/production"
EXPECTED_GROWTH = {"aftersales_model_metrics", "aftersales_lb_model_metrics"}
LB = ["dealers", "parts", "forecast_weekly", "stockout_risk", "model_metrics"]
SNAP_DIR = Path("evidence/aftersales/pipeline/snapshots")


def sql(a, stmt):
    res = subprocess.run(["databricks", "experimental", "aitools", "tools", "query", "-p", a.profile, "-w", a.warehouse,
                          "-o", "json", stmt], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip()[-300:])
    return json.loads(res.stdout or "[]")


def cli(a, *args):
    res = subprocess.run(["databricks", *args, "-p", a.profile, "-o", "json"], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip()[-300:])
    return json.loads(res.stdout or "null")


def uc_model(a):
    m = cli(a, "registered-models", "get", MODEL, "--include-aliases")
    vs = cli(a, "model-versions", "list", MODEL)
    return {"aliases": {x["alias_name"]: str(x["version_num"]) for x in (m.get("aliases") or [])},
            "versions": sorted(str(v["version"]) for v in vs)}


def postgres(a):
    import os
    ep = cli(a, "postgres", "list-endpoints", BRANCH)[0]["name"]
    host = cli(a, "postgres", "get-endpoint", ep)["status"]["hosts"]["host"]
    user = cli(a, "current-user", "me")["userName"]
    env = dict(os.environ, PGPASSWORD=cli(a, "postgres", "generate-database-credential", ep)["token"])
    out = {}
    for t in LB:
        cols = subprocess.run(["psql", f"host={host} user={user} dbname=databricks_postgres sslmode=require", "-X", "-A", "-t", "-c",
                               f"SELECT string_agg(quote_ident(column_name), ',' ORDER BY ordinal_position) FROM information_schema.columns "
                               f"WHERE table_schema='{a.schema}' AND table_name='aftersales_lb_{t}'"],
                              capture_output=True, text=True, env=env).stdout.strip()
        keep = ",".join(c for c in cols.split(",") if c.strip('"') not in VOLATILE)
        q = (f"BEGIN READ ONLY; SELECT count(*) || ' ' || md5(coalesce(string_agg(r::text, '|' ORDER BY r::text), '')) "
             f"FROM (SELECT {keep} FROM \"{a.schema}\".aftersales_lb_{t}) r; COMMIT;")
        res = subprocess.run(["psql", f"host={host} user={user} dbname=databricks_postgres sslmode=require", "-X", "-A", "-t", "-c", q],
                             capture_output=True, text=True, env=env)
        line = [l for l in res.stdout.splitlines() if l and l not in ("BEGIN", "COMMIT")]
        n, fp = (line[0].split() + ["?", "?"])[:2] if line else ("ERR", res.stderr.strip()[-120:])
        out[f"aftersales_lb_{t}"] = {"rows": n, "fingerprint": fp}
    return out


def landing(a):
    import hashlib
    import shutil
    import tempfile
    import os
    d = tempfile.mkdtemp(prefix="aftersales-landing-", dir=os.environ.get("TEAM_SCRATCH"))
    try:
        res = subprocess.run(["databricks", "fs", "cp", "-r", LANDING, d, "-p", a.profile], capture_output=True, text=True)
        if res.returncode != 0:
            return {"error": res.stderr.strip()[-200:]}
        files = sorted(f for f in Path(d).rglob("*") if f.is_file())
        h = hashlib.sha256()
        for f in files:
            h.update(str(f.relative_to(d)).encode()); h.update(hashlib.sha256(f.read_bytes()).digest())
        return {"files": len(files), "tree_sha256": h.hexdigest(), "bytes": sum(f.stat().st_size for f in files)}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def snap(a):
    cols = sql(a, f"""SELECT table_name, column_name FROM {a.catalog}.information_schema.columns
                      WHERE table_schema = '{a.schema}' AND table_name LIKE 'aftersales\\_%' ORDER BY table_name, ordinal_position""")
    by_table = {}
    for c in cols:
        by_table.setdefault(c["table_name"], []).append(c["column_name"])
    out = {"label": a.label, "taken_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "tables": {}}
    for t, cs in sorted(by_table.items()):
        if t.startswith("aftersales_lb_"):
            continue  # synced tables: fingerprinted on the Postgres side below
        keep = [c for c in cs if c not in VOLATILE]
        expr = ", ".join(f"`{c}`" for c in keep)
        r = sql(a, f"SELECT count(*) n, cast(sum(cast(xxhash64({expr}) AS DECIMAL(38,0))) AS STRING) fp FROM {a.catalog}.{a.schema}.`{t}`")[0]
        out["tables"][t] = {"rows": int(r["n"]), "fingerprint": r["fp"], "excluded": sorted(set(cs) & VOLATILE)}
    out["model_versions"] = sql(a, f"SELECT model_version, model_name, is_champion FROM {a.catalog}.{a.schema}.aftersales_model_metrics ORDER BY 1")
    out["ml_model_version_in_tables"] = sql(a, f"""SELECT 'forecast' t, array_join(collect_set(model_version), ',') v FROM {a.catalog}.{a.schema}.aftersales_forecast_weekly
        UNION ALL SELECT 'risk', array_join(collect_set(model_version), ',') FROM {a.catalog}.{a.schema}.aftersales_stockout_risk""")
    out["uc_model"] = uc_model(a)
    out["postgres"] = postgres(a)
    out["landing"] = landing(a)
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    (SNAP_DIR / f"{a.label}.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


def diff(a):
    b = json.loads((SNAP_DIR / f"{a.before}.json").read_text())
    c = json.loads((SNAP_DIR / f"{a.after}.json").read_text())
    lines, fails = [], 0
    for t in sorted(set(b["tables"]) | set(c["tables"])):
        x, y = b["tables"].get(t), c["tables"].get(t)
        if t in EXPECTED_GROWTH:  # history table: a rerun adds the new version's row, the old champion flips
            ok = x is not None and y is not None and y["rows"] == x["rows"] + 1
            fails += 0 if ok else 1
            lines.append(f"{'PASS' if ok else 'FAIL'}\t{t}\trows {x and x['rows']} -> {y and y['rows']} (expected +1)\tcontent changes by design")
            continue
        ok = x is not None and y is not None and x["rows"] == y["rows"] and x["fingerprint"] == y["fingerprint"]
        fails += 0 if ok else 1
        lines.append(f"{'PASS' if ok else 'FAIL'}\t{t}\trows {x and x['rows']} -> {y and y['rows']}\t"
                     f"fp {'same' if ok else (x and x['fingerprint'], y and y['fingerprint'])}")
    # Postgres serving tables: identical rows + content (excluding run-time columns)
    for t in sorted(set(b.get("postgres", {})) | set(c.get("postgres", {}))):
        x, y = b["postgres"].get(t), c["postgres"].get(t)
        if t in EXPECTED_GROWTH:
            ok = x is not None and y is not None and int(y["rows"]) == int(x["rows"]) + 1
            fails += 0 if ok else 1
            lines.append(f"{'PASS' if ok else 'FAIL'}\tpostgres {t}\trows {x and x['rows']} -> {y and y['rows']} (expected +1)\t")
            continue
        ok = x == y and x is not None and x["rows"] not in ("ERR", "?")
        fails += 0 if ok else 1
        lines.append(f"{'PASS' if ok else 'FAIL'}\tpostgres {t}\trows {x and x['rows']} -> {y and y['rows']}\tmd5 {'same' if ok else (x, y)}")
    # landing files byte-identical
    x, y = b.get("landing", {}), c.get("landing", {})
    ok = x.get("tree_sha256") and x == y
    fails += 0 if ok else 1
    lines.append(f"{'PASS' if ok else 'FAIL'}\tlanding files byte-identical\t{x.get('files')} files {x.get('bytes')} B "
                 f"sha {str(x.get('tree_sha256'))[:16]} -> {y.get('files')} files sha {str(y.get('tree_sha256'))[:16]}")
    # model: a rerun registers a new version and moves @champion to it; metrics gain exactly one row
    mb, mc = b.get("uc_model", {}), c.get("uc_model", {})
    new = sorted(set(mc.get("versions", [])) - set(mb.get("versions", [])), key=int)
    champ_b, champ_c = mb.get("aliases", {}).get("champion"), mc.get("aliases", {}).get("champion")
    ok = len(new) == 1 and champ_c == new[0] and champ_b != champ_c
    fails += 0 if ok else 1
    lines.append(f"{'PASS' if ok else 'FAIL'}\tUC model: one new version and @champion moved to it\t"
                 f"versions {mb.get('versions')} -> {mc.get('versions')}, @champion {champ_b} -> {champ_c}")
    nb, nc = len(b.get("model_versions", [])), len(c.get("model_versions", []))
    champs = [r["model_version"] for r in c.get("model_versions", []) if str(r.get("is_champion")).lower() == "true"]
    ok = nc == nb + 1 and champs == [champ_c]
    fails += 0 if ok else 1
    lines.append(f"{'PASS' if ok else 'FAIL'}\taftersales_model_metrics gains 1 row, single is_champion = new version\t{nb} -> {nc} rows, champion rows {champs}")
    used = {r["t"]: r["v"] for r in c.get("ml_model_version_in_tables", [])}
    ok = used.get("forecast") == champ_c and used.get("risk") == champ_c
    fails += 0 if ok else 1
    lines.append(f"{'PASS' if ok else 'FAIL'}\tforecast/risk model_version == new champion\t{used}")
    head = [f"# claim:   a full rerun of the aftersales job leaves every aftersales_* table unchanged (rows + content)",
            f"# command: python3 -I tests/aftersales/snapshot.py diff {a.before} {a.after}",
            f"# before:  {b['taken_at']}   after: {c['taken_at']}",
            f"# excluded run-time columns: {sorted(VOLATILE)}",
            f"# result:  {'PASS' if fails == 0 else f'FAIL ({fails})'}  tables={len(lines)}", ""]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(head + lines) + "\n", encoding="utf-8")
    print("\n".join(head + lines))
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snap")
    s.add_argument("label")
    d = sub.add_parser("diff")
    d.add_argument("before")
    d.add_argument("after")
    d.add_argument("--out", default="evidence/aftersales/pipeline/idempotency.txt")
    for p in (s,):
        p.add_argument("--profile", required=True)
        p.add_argument("--warehouse", required=True)
        p.add_argument("--catalog", default="classic_stable")
        p.add_argument("--schema", default="auto_intelligence")
    a = ap.parse_args()
    return snap(a) if a.cmd == "snap" else diff(a)


if __name__ == "__main__":
    sys.exit(main())
