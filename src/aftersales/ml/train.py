"""Task `train`: honest backtest vs seasonal-naive, MLflow tracking, UC registration, @champion gate.

Args: --catalog --schema --experiment [--holdout-weeks 13]
Gate (ADR D3): @champion moves only if WAPE < 0.95 x baseline WAPE. Otherwise the version is registered
WITHOUT the alias, the metrics row is still written, and the task fails loudly (the old champion stays).
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile

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

from aftersales.ml import forecast as fc  # noqa: E402
from aftersales.ml.spark_io import MODEL_BASENAME, get_spark, load_inputs  # noqa: E402
from aftersales.ml.tables import ensure_table, overwrite  # noqa: E402

HORIZONS_BACKTEST = list(range(1, 14))
GATE_FACTOR = 0.95


def wape_by_category(pred: pd.DataFrame, parts: pd.DataFrame) -> dict:
    """Per-category WAPE with plain aggregations (no groupby.apply: kwargs differ across pandas versions)."""
    d = pred.merge(parts[["part_id", "category_id"]], on="part_id")
    d["abs_err"] = (d["actual"] - d["forecast"]).abs()
    g = d.groupby("category_id")[["abs_err", "actual"]].sum()
    return {c: float(r.abs_err / r.actual) for c, r in g.iterrows() if r.actual > 0}


def build_panel(inputs: dict) -> fc.Panel:
    static = fc.encode_static(inputs["parts"], inputs["dealers"])
    return fc.Panel.from_frame(inputs["demand"], static=static)


def run(spark, catalog: str, schema: str, experiment: str, holdout_weeks: int = 13, registry_uri: str = "databricks-uc") -> None:
    import mlflow
    import mlflow.sklearn  # noqa: F401
    from mlflow.models import infer_signature

    prefix = f"{catalog}.{schema}"
    model_name = f"{prefix}.{MODEL_BASENAME}"
    inputs = load_inputs(spark, prefix)
    panel = build_panel(inputs)
    last_week = panel.weeks[-1]
    cutoff = last_week + pd.Timedelta(days=6) - pd.Timedelta(weeks=holdout_weeks)   # Sunday before the holdout
    forecast_date = last_week + pd.Timedelta(weeks=1)

    mlflow.set_registry_uri(registry_uri)
    mlflow.set_experiment(experiment)
    client = mlflow.MlflowClient()

    with mlflow.start_run(run_name=f"backtest-{cutoff.date()}") as run:
        bt = fc.backtest(panel, cutoff, range(1, holdout_weeks + 1))
        by_cat = wape_by_category(bt.predictions, inputs["parts"])
        mlflow.log_params({"cutoff": str(cutoff.date()), "holdout_weeks": holdout_weeks, "strategy": "direct",
                           "model": "HistGradientBoostingRegressor(poisson)", "seed": fc.SEED, "season": fc.SEASON,
                           "n_series": bt.n_series, "gate_factor": GATE_FACTOR, "last_actual_week": str(last_week.date())})
        mlflow.log_metrics({"wape": bt.wape_model, "baseline_wape": bt.wape_baseline, "bias": bt.bias_model,
                            "baseline_bias": bt.bias_baseline, "lift_vs_baseline": bt.lift,
                            **{f"wape_{c}": v for c, v in by_cat.items()},
                            **{f"wape_h{h}": v for h, v in bt.wape_by_h.items()}})
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "backtest_predictions.parquet")
            bt.predictions.to_parquet(path, index=False)
            mlflow.log_artifact(path)

        passed = bt.passes_gate(GATE_FACTOR)
        # Final model refit on the full history (targets up to the last actual week), registered in UC.
        final = fc.fit(panel, HORIZONS_BACKTEST)
        sample = fc.training_set(panel.truncate(panel.weeks[-60]), [1, 2], origin_stride=8, max_origins=4)[fc.FEATURES].head(50).astype(float)
        info = mlflow.sklearn.log_model(final, name="model", signature=infer_signature(sample, final.predict(sample)),
                                        registered_model_name=model_name,
                                        serialization_format="cloudpickle")
        version = str(info.registered_model_version)
        mlflow.set_tags({"synthetic": "true", "aid_domain": "aftersales", "gate_passed": str(passed).lower()})
        print(f"backtest WAPE model={bt.wape_model:.4f} baseline={bt.wape_baseline:.4f} bias={bt.bias_model:+.4f} "
              f"lift={bt.lift:+.2%} gate={'PASS' if passed else 'FAIL'} version={version} run_id={run.info.run_id}")

        client.update_registered_model(model_name, description=(
            "Synthetic aftersales weekly demand forecaster (global HistGradientBoosting, direct multi-horizon). "
            "Aurora Motors demo, 100% synthetic data."))
        for k, v in {"synthetic": "true", "aid_domain": "aftersales"}.items():
            client.set_registered_model_tag(model_name, k, v)
        client.set_model_version_tag(model_name, version, "wape", f"{bt.wape_model:.4f}")
        client.set_model_version_tag(model_name, version, "baseline_wape", f"{bt.wape_baseline:.4f}")

        _write_metrics(spark, prefix, model_name, version, run.info.run_id, bt, cutoff, forecast_date, passed)
        if passed:  # LAST step: a failure above never leaves a champion without a metrics row
            client.set_registered_model_alias(model_name, "champion", version)

    if not passed:
        raise RuntimeError(
            f"Gate failed: WAPE {bt.wape_model:.4f} is not < {GATE_FACTOR} x baseline {bt.wape_baseline:.4f}. "
            f"Version {version} registered WITHOUT @champion; previous champion (if any) is unchanged.")


def _write_metrics(spark, prefix, model_name, version, run_id, bt, cutoff, forecast_date, passed) -> None:
    table = ensure_table(spark, prefix, "aftersales_model_metrics")
    old = spark.table(table).toPandas()
    old = old[old.model_version != version]
    if passed:
        old["is_champion"] = False
    row = pd.DataFrame([dict(
        model_name=model_name, model_version=version, run_id=run_id, cutoff_date=cutoff, forecast_date=forecast_date,
        holdout_weeks=len(bt.horizons), n_series=bt.n_series, wape=bt.wape_model, baseline_wape=bt.wape_baseline,
        bias=bt.bias_model, baseline_bias=bt.bias_baseline, is_champion=passed, logged_at=pd.Timestamp.now(tz="UTC").tz_localize(None))])
    out = pd.concat([old, row], ignore_index=True)
    overwrite(spark, table, "aftersales_model_metrics", out)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--src", default=None, help="src/ directory of the synced bundle (put on sys.path)")
    ap.add_argument("--experiment", required=True)
    ap.add_argument("--holdout-weeks", type=int, default=13)
    a = ap.parse_args(argv)
    run(get_spark(), a.catalog, a.schema, a.experiment, a.holdout_weeks)


if __name__ == "__main__":
    main()
