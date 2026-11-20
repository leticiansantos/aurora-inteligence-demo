"""`govern` job task: idempotent UC tags and comments for the aftersales tables (ADR 002, D9).

Pure statement builders take plain lists/dicts; Spark is only touched in main().
Usage: apply_tags.py --catalog <catalog> --schema <schema>
"""
import argparse
import re
import sys

# The UC model tags and description are owned by the `train` task (ADR D9), not by this task.
PREFIX = "aftersales_"

LAYER_TABLES = {
    "raw": [f"aftersales_raw_{n}" for n in ("dealers", "parts", "lead_times", "daily_sales", "stock_snapshots")],
    "silver": [f"aftersales_{n}" for n in
               ("dealers", "parts", "lead_times", "daily_sales", "stock_snapshots", "fleet_monthly")],
    "gold": ["aftersales_demand_weekly", "aftersales_stock_position"],
    "ml": ["aftersales_forecast_weekly", "aftersales_model_metrics", "aftersales_stockout_risk"],
}
TABLE_LAYER = {t: layer for layer, ts in LAYER_TABLES.items() for t in ts}

TABLE_COMMENTS = {
    "aftersales_forecast_weekly": "Synthetic weekly parts demand: history, backtest holdout forecast and 8-week "
                                  "future forecast per dealer and part. Overwritten on every score run.",
    "aftersales_model_metrics": "Synthetic-data forecast model metrics (WAPE, bias vs baseline), one row per "
                                "registered model version.",
    "aftersales_stockout_risk": "Synthetic stockout risk and recommended action per dealer, part and horizon "
                                "(14/28/56 days), derived from the demand forecast.",
}

COLUMN_COMMENTS = {
    "aftersales_forecast_weekly": {
        "dealer_id": "Synthetic dealer identifier.",
        "part_id": "Synthetic part identifier.",
        "week_start": "Monday of the forecast week.",
        "is_future": "True for future weeks, false for synthetic history.",
        "horizon_week": "Week ahead from the cutoff (1..13 holdout, 1..8 future).",
        "actual_units": "Synthetic actual demand in units (null for future weeks).",
        "sold_units": "Synthetic units actually sold (null for future weeks).",
        "forecast_units": "Forecast demand in units.",
        "lower_units": "Lower bound of the 80% prediction interval.",
        "upper_units": "Upper bound of the 80% prediction interval.",
        "baseline_units": "Naive baseline forecast in units.",
        "forecast_date": "Date the forecast was produced for.",
        "model_version": "UC model version (same version N on every row of a scoring run).",
        "scored_at": "Timestamp of the scoring run.",
    },
    "aftersales_model_metrics": {
        "model_name": "UC registered model name.",
        "model_version": "UC model version (primary key).",
        "run_id": "MLflow run id that produced the version.",
        "cutoff_date": "Last training date used for the backtest.",
        "forecast_date": "Forecast date of the evaluated version.",
        "holdout_weeks": "Number of holdout weeks in the backtest.",
        "n_series": "Number of synthetic dealer/part series evaluated.",
        "wape": "Weighted absolute percentage error of the model on the holdout.",
        "baseline_wape": "WAPE of the naive baseline on the same holdout.",
        "bias": "Sum(forecast - actual) / sum(actual) of the model.",
        "baseline_bias": "Bias of the naive baseline.",
        "is_champion": "True if this version holds the champion alias.",
        "logged_at": "Timestamp the metrics were logged.",
    },
    "aftersales_stockout_risk": {
        "dealer_id": "Synthetic dealer identifier.",
        "part_id": "Synthetic part identifier.",
        "horizon_days": "Risk horizon in days (14, 28 or 56).",
        "forecast_date": "Forecast date the risk is based on.",
        "stock_units": "Synthetic on-hand units at the latest snapshot.",
        "on_order_units": "Units already on order.",
        "available_units": "On-hand plus on-order units.",
        "lead_time_days": "Supplier lead time in days.",
        "forecast_units": "Forecast demand over the horizon, in units.",
        "forecast_sigma_units": "Forecast standard deviation over the horizon.",
        "safety_stock_units": "Safety stock in units.",
        "days_of_stock": "Days the available stock is expected to last.",
        "days_to_stockout": "Days until the projected stockout.",
        "stockout_probability": "Probability of a stockout within the horizon.",
        "risk_level": "Risk level: critical, high, medium or low.",
        "shortfall_units": "Projected shortfall in units.",
        "lost_sales_brl": "Projected lost sales in BRL (synthetic prices).",
        "action": "Recommended action: reorder, transfer or monitor.",
        "recommended_qty": "Recommended quantity to order or transfer.",
        "transfer_from_dealer_id": "Dealer with excess stock to transfer from, if any.",
        "transfer_from_excess_units": "Excess units available at the source dealer.",
        "model_version": "UC model version used for scoring.",
        "scored_at": "Timestamp of the scoring run.",
    },
}

# Statement forms tried in order for each table type; the first that works wins.
ALTER_KEYWORDS = {
    "MATERIALIZED_VIEW": ["MATERIALIZED VIEW", "TABLE"],
    "STREAMING_TABLE": ["STREAMING TABLE", "TABLE"],
    "VIEW": ["VIEW", "TABLE"],
}
DEFAULT_ALTER_KEYWORDS = ["TABLE"]


def qi(name):
    return "`" + name.replace("`", "``") + "`"


def fq(catalog, schema, name):
    return ".".join(qi(p) for p in (catalog, schema, name))


def lit(text):
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def tags_for(table):
    return {"synthetic": "true", "aid_domain": "aftersales", "layer": TABLE_LAYER[table]}


def tag_clause(tags):
    return ", ".join(f"{lit(k)} = {lit(v)}" for k, v in tags.items())


def set_tags_sql(keyword, full_name, tags):
    return f"ALTER {keyword} {full_name} SET TAGS ({tag_clause(tags)})"


def table_comment_sql(full_name, text):
    return f"COMMENT ON TABLE {full_name} IS {lit(text)}"


def column_comment_sqls(full_name, table, existing_columns):
    return [f"ALTER TABLE {full_name} ALTER COLUMN {qi(c)} COMMENT {lit(t)}"
            for c, t in COLUMN_COMMENTS.get(table, {}).items() if c in set(existing_columns)]


def plan_tables(existing):
    """existing: {table_name: table_type}. Returns (to_govern, missing, unknown)."""
    to_govern = sorted(t for t in existing if t in TABLE_LAYER)
    missing = sorted(t for t in TABLE_LAYER if t not in existing)
    unknown = sorted(t for t in existing if t.startswith(PREFIX) and t not in TABLE_LAYER)
    return to_govern, missing, unknown


def try_forms(execute, statements):
    """Run alternatives until one succeeds. Returns (ok, last_error)."""
    err = None
    for s in statements:
        try:
            execute(s)
            return re.match(r"ALTER (.+?) \S+ SET TAGS", s).group(1), None
        except Exception as e:  # noqa: BLE001
            err = e
    return False, err


def govern(execute, query, catalog, schema, log=print):
    """execute(sql) runs a statement; query(sql) -> list of dicts. Returns the list of failures."""
    failures = []
    rows = query(
        f"SELECT table_name, table_type FROM {qi(catalog)}.information_schema.tables "
        f"WHERE table_schema = {lit(schema)} AND table_name LIKE 'aftersales\\\\_%'")
    existing = {r["table_name"]: r["table_type"] for r in rows}
    to_govern, missing, unknown = plan_tables(existing)
    for t in missing:
        log(f"WARNING: table {t} not found, skipped (expected on a first run)")
    for t in unknown:
        log(f"WARNING: unknown aftersales table {t} (not in layer map), not tagged")
    for t in to_govern:
        name = fq(catalog, schema, t)
        kws = ALTER_KEYWORDS.get(existing[t], DEFAULT_ALTER_KEYWORDS)
        ok, err = try_forms(execute, [set_tags_sql(k, name, tags_for(t)) for k in kws])
        if ok:
            log(f"tagged {t} (layer={TABLE_LAYER[t]}) via ALTER {ok} [table_type={existing[t]}]")
        else:
            failures.append(f"tags {t}: {err}")
        if t in TABLE_COMMENTS:
            try:
                execute(table_comment_sql(name, TABLE_COMMENTS[t]))
                cols = [r["column_name"] for r in query(
                    f"SELECT column_name FROM {qi(catalog)}.information_schema.columns "
                    f"WHERE table_schema = {lit(schema)} AND table_name = {lit(t)}")]
                for s in column_comment_sqls(name, t, cols):
                    execute(s)
                log(f"commented {t}")
            except Exception as e:  # noqa: BLE001
                failures.append(f"comments {t}: {e}")
    attempted_ok = [t for t in to_govern if not any(f.startswith(f"tags {t}:") for f in failures)]
    failures.extend(verify_tags(query, catalog, schema, attempted_ok, log))
    return failures


def verify_tags(query, catalog, schema, tables, log=print):
    """Post-check: every governed existing table must carry synthetic, aid_domain and layer."""
    rows = query(
        f"SELECT table_name, tag_name FROM {qi(catalog)}.information_schema.table_tags "
        f"WHERE schema_name = {lit(schema)} AND table_name LIKE 'aftersales\\\\_%'")
    have = {}
    for r in rows:
        have.setdefault(r["table_name"], set()).add(r["tag_name"])
    out = []
    for t in tables:
        lacking = sorted({"synthetic", "aid_domain", "layer"} - have.get(t, set()))
        if lacking:
            out.append(f"verify {t}: missing tags {lacking}")
    log(f"tag verification: {len(tables) - len(out)}/{len(tables)} tables carry synthetic, aid_domain and layer")
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--catalog", required=True)
    p.add_argument("--schema", required=True)
    args, _unknown = p.parse_known_args(argv)
    from pyspark.sql import SparkSession

    spark = SparkSession.builder.getOrCreate()
    failures = govern(lambda s: spark.sql(s),
                      lambda s: [r.asDict() for r in spark.sql(s).collect()],
                      args.catalog, args.schema)
    for f in failures:
        print(f"ERROR: {f}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    # Serverless runs the file via exec() in IPython, where ANY sys.exit (even 0) marks the task failed.
    rc = main()
    if rc:
        raise RuntimeError(f"govern failed (rc={rc})")
