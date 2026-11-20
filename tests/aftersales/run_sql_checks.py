"""Run the SQL oracles in tests/aftersales/sql/*.sql (read-only SELECTs) and write text evidence.

Every query returns rows (check, ok, detail); a check passes when ok is true. Files can be selected by
prefix, so checks can be run as each layer lands (e.g. --only 01,02,03 after the pipeline).

Usage:
  python3 -I tests/aftersales/run_sql_checks.py --profile classic-stable-new --warehouse 754bcdfc4beaaaa1 \
      [--catalog classic_stable --schema auto_intelligence] [--only 01,02] [--out evidence/aftersales/sql-checks.txt]
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--warehouse", required=True)
    ap.add_argument("--catalog", default="classic_stable")
    ap.add_argument("--schema", default="auto_intelligence")
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default="evidence/aftersales/sql-checks.txt")
    a = ap.parse_args()
    prefixes = [p for p in a.only.split(",") if p]
    files = sorted(f for f in (HERE / "sql").glob("*.sql") if not prefixes or any(f.name.startswith(p) for p in prefixes))
    lines, fails, total = [], 0, 0
    for f in files:
        stmt = f.read_text(encoding="utf-8").replace("__T__", f"{a.catalog}.{a.schema}.")
        res = subprocess.run(["databricks", "experimental", "aitools", "tools", "query", "-p", a.profile,
                              "-w", a.warehouse, "-o", "json"], input=stmt, capture_output=True, text=True)  # stdin: a leading "--" comment would parse as a flag
        lines.append(f"## {f.name}")
        if res.returncode != 0:
            fails += 1
            total += 1
            lines.append(f"ERROR\t{f.name}\t{res.stderr.strip().splitlines()[-1][:300] if res.stderr.strip() else 'no output'}")
            continue
        for row in json.loads(res.stdout or "[]"):
            total += 1
            ok = str(row.get("ok")).lower() == "true"
            soft = str(row.get("check", "")).startswith("QA-judgement:")  # not an ADR rule: WARN, never FAIL
            fails += 0 if ok or soft else 1
            status = "PASS" if ok else ("WARN" if soft else "FAIL")
            lines.append(f"{status}\t{row.get('check')}\t{(row.get('detail') or '')[:400]}")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    head = ["# claim:   aftersales tables satisfy the frozen contract (docs/data-model/aftersales.md) and the QA oracles",
            f"# command: python3 -I tests/aftersales/run_sql_checks.py --catalog {a.catalog} --schema {a.schema}"
            + (f" --only {a.only}" if a.only else ""),
            f"# date:    {now}  qa git: {sha}",
            f"# result:  {'PASS' if fails == 0 else f'FAIL ({fails})'}  checks={total}", ""]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(head + lines) + "\n", encoding="utf-8")
    print("\n".join(head + lines))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
