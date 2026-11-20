"""Reconcile pipeline monthly segment totals against the independent PDF oracle.

The oracle (tests/market/oracle/pdf_totals.csv + pdf_totals_visual_override.csv) holds
the page-1 "A) Autos" / "B) Com. Leves" month totals, read with pdftotext only.
The pipeline export is a CSV with columns: month (YYYY-MM-01), segment, units,
where segment is one of the values in SEGMENT_ALIASES.

Usage:
  python3 -I reconcile.py <pipeline_csv> <oracle_dir> [--tolerance-pct 0.05]
                          [--from YYYY-MM] [--to YYYY-MM] [--report-only]
Prints a text report; exit code 1 when any compared month is outside tolerance
(unless --report-only), 0 otherwise.
"""
import argparse
import csv
import sys
from pathlib import Path

ORACLE_COLUMNS = {"autos": "autos_month", "light_commercial": "light_commercial_month"}
SEGMENT_ALIASES = {
    "autos": "autos", "automoveis": "autos", "automóveis": "autos", "a": "autos",
    "light_commercial": "light_commercial", "comerciais_leves": "light_commercial",
    "comerciais leves": "light_commercial", "com. leves": "light_commercial", "b": "light_commercial",
}


def load_oracle(oracle_dir: Path) -> dict:
    """Return {(month, segment): (units, source)} with manual overrides applied."""
    oracle = {}
    for name in ("pdf_totals.csv", "pdf_totals_visual_override.csv"):
        path = oracle_dir / name
        if not path.exists():
            continue
        with path.open(newline="") as fh:
            for row in csv.DictReader(fh):
                status = row["parse_status"]
                if status != "ok" and status != "manual_visual_read":
                    continue
                for seg, col in ORACLE_COLUMNS.items():
                    if row[col]:
                        source = "pdf" if status == "ok" else "manual"
                        oracle[(row["month"][:7], seg)] = (int(row[col]), f"{row['source_file']}:{source}")
    return oracle


def load_pipeline(path: Path) -> dict:
    """Return {(month, segment): units} summed over input rows."""
    totals = {}
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        if not {"month", "segment", "units"} <= set(reader.fieldnames or []):
            first = path.read_text().strip().splitlines()[:3]
            print("pipeline export is not a CSV with columns month,segment,units:\n  " + "\n  ".join(first))
            print("\nRESULT: FAIL")
            raise SystemExit(1)
        for row in reader:
            seg = SEGMENT_ALIASES.get(row["segment"].strip().lower())
            if seg is None:
                raise SystemExit(f"unknown segment value in pipeline export: {row['segment']!r}")
            key = (row["month"][:7], seg)
            totals[key] = totals.get(key, 0) + int(float(row["units"]))
    return totals


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pipeline_csv", type=Path)
    ap.add_argument("oracle_dir", type=Path)
    ap.add_argument("--tolerance-pct", type=float, default=0.05)
    ap.add_argument("--from", dest="from_month", default="0000-00")
    ap.add_argument("--to", dest="to_month", default="9999-99")
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--report-only-months", default="",
                    help="comma-separated YYYY-MM compared but never failing (e.g. OCR-only PDFs)")
    args = ap.parse_args()

    soft = {m.strip()[:7] for m in args.report_only_months.split(",") if m.strip()}
    oracle = load_oracle(args.oracle_dir)
    pipeline = load_pipeline(args.pipeline_csv)
    in_window = lambda k: args.from_month <= k[0] <= args.to_month  # noqa: E731

    keys = sorted(k for k in set(oracle) | set(pipeline) if in_window(k))
    fails, soft_outside, missing_pipeline, missing_oracle, compared = [], [], [], [], 0
    lines = [f"{'month':7}  {'segment':16} {'pdf_total':>10} {'pipeline':>10} {'diff':>8} {'diff_pct':>8}  status  source"]
    for key in keys:
        exp = oracle.get(key)
        got = pipeline.get(key)
        if exp is None:
            missing_oracle.append(key)
            continue
        if got is None:
            if key[0] not in soft:
                missing_pipeline.append(key)
            lines.append(f"{key[0]:7}  {key[1]:16} {exp[0]:>10} {'-':>10} {'-':>8} {'-':>8}  MISSING {exp[1]}")
            continue
        compared += 1
        diff = got - exp[0]
        pct = 100.0 * diff / exp[0] if exp[0] else float("inf")
        ok = abs(pct) <= args.tolerance_pct
        label = "ok" if ok else ("REPORT" if key[0] in soft else "FAIL")
        if label == "FAIL":
            fails.append(key)
        elif label == "REPORT":
            soft_outside.append(key)
        lines.append(f"{key[0]:7}  {key[1]:16} {exp[0]:>10} {got:>10} {diff:>8} {pct:>7.3f}%  {label:7} {exp[1]}")

    print(f"tolerance: |diff| <= {args.tolerance_pct}% of the PDF page-1 total; window {args.from_month}..{args.to_month}")
    if soft:
        print(f"report-only months (never fail): {', '.join(sorted(soft))}")
    print(f"compared: {compared}  within_tolerance: {compared - len(fails) - len(soft_outside)}  outside: {len(fails)}  outside_report_only: {len(soft_outside)}  "
          f"missing_in_pipeline: {len(missing_pipeline)}  not_in_oracle: {len(missing_oracle)}")
    if missing_oracle:
        print("not_in_oracle (pipeline months without a local PDF; not compared): "
              + ", ".join(f"{m}/{s}" for m, s in missing_oracle))
    print()
    print("\n".join(lines))
    failed = bool(fails or missing_pipeline)
    print(f"\nRESULT: {'FAIL' if failed else 'PASS'}")
    return 1 if failed and not args.report_only else 0


if __name__ == "__main__":
    sys.exit(main())
