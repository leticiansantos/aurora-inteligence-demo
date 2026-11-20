"""UC model + MLflow checks for the aftersales forecaster (ADR 002 D3). Read-only CLI/SQL calls.

- @champion alias exists, points to a READY version, and the forecast/risk tables use that version
- the champion's MLflow run logged the D3 params (cutoff 2026-08-16, 13 holdout weeks, 720 series, season 52,
  seed fixed) and passes the gate WAPE < 0.95 x baseline WAPE
- aftersales_model_metrics row of the champion == the run's logged metrics; exactly one is_champion row
- versions without alias and without a metrics row are reported as orphans (allowed by D3), never as champion
- model carries a comment (D9 tags on the model are checked by hand in the UC UI/API; not exposed here)

Usage: python3 -I tests/aftersales/check_model.py --profile P --warehouse W [--out evidence/aftersales/ml/model-registry.txt]
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

MODEL = "classic_stable.auto_intelligence.aftersales_demand_forecaster"
T = "classic_stable.auto_intelligence."


def cli(a, *args):
    res = subprocess.run(["databricks", *args, "-p", a.profile, "-o", "json"], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip()[-300:])
    return json.loads(res.stdout or "null")


def sql(a, stmt):
    res = subprocess.run(["databricks", "experimental", "aitools", "tools", "query", "-p", a.profile, "-w", a.warehouse,
                          "-o", "json"], input=stmt, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip()[-300:])
    return json.loads(res.stdout or "[]")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--warehouse", required=True)
    ap.add_argument("--out", default="evidence/aftersales/ml/model-registry.txt")
    a = ap.parse_args()
    lines, fails = [], 0

    def rec(ok, label, detail=""):
        nonlocal fails
        fails += 0 if ok else 1
        lines.append(f"{'PASS' if ok else 'FAIL'}\t{label}\t{detail}")

    m = cli(a, "registered-models", "get", MODEL, "--include-aliases")
    aliases = {x["alias_name"]: str(x["version_num"]) for x in (m.get("aliases") or [])}
    champ = aliases.get("champion")
    rec(champ is not None, "@champion alias exists", json.dumps(aliases))
    rec(bool((m.get("comment") or "").strip()), "model has a comment", (m.get("comment") or "")[:80])
    versions = cli(a, "model-versions", "list", MODEL)
    metrics = {r["model_version"]: r for r in sql(a, f"SELECT * FROM {T}aftersales_model_metrics")}
    nchamp = sum(1 for r in metrics.values() if str(r.get("is_champion")).lower() == "true")
    rec(nchamp == 1, "exactly one is_champion row in aftersales_model_metrics", f"n={nchamp}")
    for v in sorted(versions, key=lambda v: int(v["version"])):
        ver = str(v["version"])
        has_metrics = ver in metrics
        if ver != champ and not has_metrics:
            lines.append(f"INFO\tversion {ver}: orphan (no alias, no metrics row; allowed by ADR D3)\trun {v.get('run_id')}")
            continue
        run = cli(a, "experiments", "get-run", v["run_id"])["run"]
        params = {p["key"]: p["value"] for p in run["data"].get("params", [])}
        rm = {x["key"]: x["value"] for x in run["data"].get("metrics", [])}
        tag = f"version {ver}{' (@champion)' if ver == champ else ''}"
        rec(v.get("status") == "READY", f"{tag}: READY", v.get("status"))
        exp = {"cutoff": "2026-08-16", "holdout_weeks": "13", "n_series": "720", "season": "52"}
        rec(all(params.get(k) == x for k, x in exp.items()) and "seed" in params, f"{tag}: run params match D3",
            json.dumps({k: params.get(k) for k in [*exp, "seed", "gate_factor", "strategy"]}))
        w, b = rm.get("wape"), rm.get("baseline_wape")
        rec(w is not None and b is not None and w < 0.95 * b, f"{tag}: gate WAPE < 0.95 x baseline",
            f"wape={w} baseline={b} ratio={w / b if w and b else None}")
        if has_metrics:
            row = metrics[ver]
            same = all(abs(float(row[k]) - float(rm[k])) < 1e-9 for k in ("wape", "baseline_wape", "bias", "baseline_bias") if k in rm)
            rec(same and row.get("run_id") == v["run_id"], f"{tag}: metrics table row == MLflow run metrics",
                f"table wape={row['wape']} run wape={rm.get('wape')} run_id_match={row.get('run_id') == v['run_id']}")
            rec((str(row.get("is_champion")).lower() == "true") == (ver == champ), f"{tag}: is_champion matches alias")
        elif ver == champ:
            rec(False, f"{tag}: champion has a metrics row")
    used = sql(a, f"""SELECT 'forecast' t, collect_set(model_version) v FROM {T}aftersales_forecast_weekly
                      UNION ALL SELECT 'risk', collect_set(model_version) FROM {T}aftersales_stockout_risk""")
    for r in used:
        vs = r["v"] if isinstance(r["v"], list) else json.loads(r["v"])
        rec(vs == [champ] or vs == [f"{champ}"], f"aftersales_{r['t']}: model_version == champion {champ}", json.dumps(vs))

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    head = [f"# claim:   {MODEL} @champion passes the D3 gate, its MLflow run matches aftersales_model_metrics, and the scored tables use it",
            "# command: python3 -I tests/aftersales/check_model.py",
            f"# date:    {now}  qa git: {sha}",
            f"# result:  {'PASS' if fails == 0 else f'FAIL ({fails})'}", ""]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(head + lines) + "\n", encoding="utf-8")
    print("\n".join(head + lines))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
