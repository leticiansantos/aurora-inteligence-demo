"""Task `score`: forecast (backtest + 8 future weeks) and stockout risk with the @champion model.

Args: --catalog --schema
Idempotent: both ML tables are fully overwritten; the output is a pure function of (champion version, inputs)
except for `scored_at`. Backtest rows come from the champion's own training run (artifact), so they carry
the same model_version as the future rows (ADR D4 / QA review).
"""
from __future__ import annotations

import argparse
import os
import sys

def _bootstrap_src(argv=None) -> None:
    """Put `src/` on sys.path: explicit --src wins (deterministic on serverless, where __file__ may be undefined)."""
    argv = sys.argv if argv is None else argv
    src = None
    for i, a in enumerate(argv):
        if a == "--src" and i + 1 < len(argv):
            src = argv[i + 1]
        elif a.startswith("--src="):
            src = a.split("=", 1)[1]
    if src:
        sys.path.insert(0, src)
        return
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    except NameError:
        sys.path.insert(0, os.getcwd())


_bootstrap_src()

import pandas as pd  # noqa: E402

from aftersales.ml import assemble, forecast as fc, risk  # noqa: E402
from aftersales.ml.spark_io import MODEL_BASENAME, get_spark, load_inputs  # noqa: E402
from aftersales.ml.tables import ensure_table, overwrite  # noqa: E402
from aftersales.ml.train import build_panel  # noqa: E402

FUTURE_HORIZONS = list(range(1, 9))


def check_invariants(inputs, fw, rk, sigma, future) -> None:
    n = len(inputs["stock"])
    problems = []
    if len(fw) != n * 34:
        problems.append(f"forecast_weekly rows {len(fw)} != {n} x 34")
    if len(rk) != n * 3:
        problems.append(f"stockout_risk rows {len(rk)} != {n} x 3")
    keys = inputs["stock"][["dealer_id", "part_id"]].drop_duplicates()
    if len(keys) != n:
        problems.append("duplicate keys in aftersales_stock_position")
    for name, df in (("sigma", sigma), ("future forecast", future)):
        miss = len(keys.merge(df[["dealer_id", "part_id"]].drop_duplicates(), how="left", indicator=True).query("_merge != 'both'"))
        if miss:
            problems.append(f"{miss} stock rows without {name}")
    if fw.duplicated(["dealer_id", "part_id", "week_start"]).any() or rk.duplicated(["dealer_id", "part_id", "horizon_days"]).any():
        problems.append("duplicate primary keys")
    if problems:
        raise RuntimeError("score invariants violated: " + "; ".join(problems))


def run(spark, catalog: str, schema: str, registry_uri: str = "databricks-uc") -> None:
    import mlflow
    import mlflow.sklearn  # noqa: F401

    prefix = f"{catalog}.{schema}"
    model_name = f"{prefix}.{MODEL_BASENAME}"
    mlflow.set_registry_uri(registry_uri)
    client = mlflow.MlflowClient()
    mv = client.get_model_version_by_alias(model_name, "champion")   # raises if there is no champion
    version = str(mv.version)
    model = mlflow.sklearn.load_model(f"models:/{model_name}/{version}")   # the version read above, not a 2nd alias lookup

    inputs = load_inputs(spark, prefix)
    panel = build_panel(inputs)
    path = mlflow.artifacts.download_artifacts(run_id=mv.run_id, artifact_path="backtest_predictions.parquet")
    bt = pd.read_parquet(path)
    bt["week_start"] = pd.to_datetime(bt["week_start"])
    expected_last = panel.weeks[-1]
    if bt["week_start"].max() != expected_last:
        raise RuntimeError(f"Champion v{version} was backtested up to {bt['week_start'].max().date()} but the data "
                           f"ends at {expected_last.date()}: run `train` again before `score`.")

    future = fc.predict(model, panel, FUTURE_HORIZONS)
    sigma = assemble.series_sigma(bt)
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    forecast_date = expected_last + pd.Timedelta(weeks=1)

    fw = assemble.build_forecast_weekly(inputs["demand"], bt, future, sigma, model_version=version, scored_at=now)
    stock = inputs["stock"]
    rk = risk.compute_risk(stock, inputs["parts"], inputs["dealers"], future.rename(columns={"h": "horizon_week", "forecast": "forecast_units"}), sigma)
    rk = assemble.build_stockout_risk(rk, forecast_date=forecast_date, model_version=version, scored_at=now)

    check_invariants(inputs, fw, rk, sigma, future)
    n1 = overwrite(spark, ensure_table(spark, prefix, "aftersales_forecast_weekly"), "aftersales_forecast_weekly", fw)
    n2 = overwrite(spark, ensure_table(spark, prefix, "aftersales_stockout_risk"), "aftersales_stockout_risk", rk)
    print(f"scored champion v{version}: aftersales_forecast_weekly={n1} rows, aftersales_stockout_risk={n2} rows")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--src", default=None, help="src/ directory of the synced bundle (put on sys.path)")
    a = ap.parse_args(argv)
    run(get_spark(), a.catalog, a.schema)


if __name__ == "__main__":
    main()
