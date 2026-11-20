"""Deterministic CSV/JSON writer for the aftersales landing files (pure Python, no Spark)."""
import csv
import json
import os

from aftersales_config import DEFAULT_CONFIG, AftersalesConfig
from aftersales_generator import dealers_rows, lead_times_rows, parts_rows, simulate

DEALERS_HEADER = ["dealer_id", "dealer_name", "city", "state", "region", "opened_on", "fleet_share"]
PARTS_HEADER = ["part_id", "part_name", "category_id", "category_name", "unit_price_brl", "unit_cost_brl", "is_critical"]
LEAD_HEADER = ["dealer_id", "part_id", "lead_time_days"]
SALES_HEADER = ["sale_date", "dealer_id", "part_id", "demand_units", "sold_units", "lost_units"]
SNAP_HEADER = ["snapshot_date", "dealer_id", "part_id", "on_hand_units", "on_order_units"]


def _write_csv(path: str, header: list, rows: list) -> int:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:  # overwrite: same name, same bytes
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    return len(rows)


def write_all(out_dir: str, fleet: dict, cfg: AftersalesConfig = DEFAULT_CONFIG) -> dict:
    """Write every landing file under out_dir; returns row counts per entity."""
    counts = {
        "dealers": _write_csv(os.path.join(out_dir, "dealers", "dealers.csv"), DEALERS_HEADER, dealers_rows()),
        "parts": _write_csv(os.path.join(out_dir, "parts", "parts.csv"), PARTS_HEADER, parts_rows()),
        "lead_times": _write_csv(
            os.path.join(out_dir, "lead_times", "lead_times.csv"), LEAD_HEADER, lead_times_rows(cfg)),
        "daily_sales": 0,
        "stock_snapshots": 0,
    }
    cur, sales, snaps = None, [], []

    def flush():
        if cur is None:
            return
        counts["daily_sales"] += _write_csv(
            os.path.join(out_dir, "daily_sales", f"daily_sales_{cur}.csv"), SALES_HEADER, sales)
        if snaps:
            counts["stock_snapshots"] += _write_csv(
                os.path.join(out_dir, "stock_snapshots", f"stock_snapshots_{cur}.csv"), SNAP_HEADER, snaps)

    for d, s_rows, n_rows in simulate(fleet, cfg):
        ym = d.strftime("%Y-%m")
        if ym != cur:
            flush()
            cur, sales, snaps = ym, [], []
        sales.extend(s_rows)
        snaps.extend(n_rows)
    flush()
    manifest = {
        "generator_version": cfg.version,
        "seed": cfg.seed,
        "history_start": cfg.history_start.isoformat(),
        "history_end": cfg.history_end.isoformat(),
        "row_counts": counts,
    }
    mpath = os.path.join(out_dir, "_manifest", "manifest.json")
    os.makedirs(os.path.dirname(mpath), exist_ok=True)
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    return counts
