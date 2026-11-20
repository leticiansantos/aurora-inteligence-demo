# Databricks notebook source
# MAGIC %md
# MAGIC # Aftersales demand forecast: backtest review (READ-ONLY)
# MAGIC Synthetic data (Aurora Motors demo). This notebook trains nothing, registers nothing and writes nothing:
# MAGIC it re-derives the backtest metrics from `aftersales_forecast_weekly` and checks them against the metrics logged by the `train` task
# MAGIC (`aftersales_model_metrics` + MLflow), then shows the UC registry state and sample forecast/risk rows.

# COMMAND ----------
import io
import sys

import mlflow
import pandas as pd


class Tee(io.StringIO):
    """Keep a copy of everything printed so the run output can be exported as plain text (see the last cell)."""
    def write(self, s):
        sys.__stdout__.write(s)
        return super().write(s)


sys.stdout = Tee()

CATALOG, SCHEMA = "classic_stable", "auto_intelligence"
P = f"{CATALOG}.{SCHEMA}"
MODEL = f"{P}.aftersales_demand_forecaster"
pd.set_option("display.width", 200, "display.max_columns", 30)

# COMMAND ----------
# MAGIC %md ## 1. Backtest WAPE recomputed from the forecast table vs the logged metrics
# MAGIC Holdout = rows with `is_future = false` and a forecast (13 weeks after the 2026-08-16 cutoff). WAPE = sum|y - yhat| / sum y.

# COMMAND ----------
holdout = spark.sql(f"""
  SELECT * FROM {P}.aftersales_forecast_weekly WHERE NOT is_future AND forecast_units IS NOT NULL""").toPandas()
y = holdout.actual_units.astype(float)
wape = (y - holdout.forecast_units.astype(float)).abs().sum() / y.sum()
wape_base = (y - holdout.baseline_units.astype(float)).abs().sum() / y.sum()
bias = (holdout.forecast_units.astype(float) - y).sum() / y.sum()
print(f"holdout rows={len(holdout)} series={holdout[['dealer_id','part_id']].drop_duplicates().shape[0]} "
      f"weeks={holdout.week_start.nunique()} ({holdout.week_start.min()} .. {holdout.week_start.max()})")
print(f"recomputed  WAPE model={wape:.4f}  baseline={wape_base:.4f}  lift={1 - wape / wape_base:+.1%}  bias={bias:+.4f}")

metrics = spark.table(f"{P}.aftersales_model_metrics").toPandas().sort_values("model_version")
print(metrics.to_string(index=False))
champ = metrics[metrics.is_champion].iloc[0]
assert abs(champ.wape - wape) < 1e-9 and abs(champ.baseline_wape - wape_base) < 1e-9 and abs(champ.bias - bias) < 1e-9
assert wape < 0.95 * wape_base, "gate: model must beat the baseline by at least 5%"
print("OK: logged champion metrics == recomputed; gate WAPE < 0.95 x baseline holds")

# COMMAND ----------
# MAGIC %md ## 2. WAPE by horizon and by part category (model vs seasonal-naive baseline)

# COMMAND ----------
parts = spark.table(f"{P}.aftersales_parts").select("part_id", "category_id", "is_critical").toPandas()
h = holdout.merge(parts, on="part_id")
h["err_m"] = (h.actual_units - h.forecast_units).abs()
h["err_b"] = (h.actual_units - h.baseline_units).abs()


def table(by):
    g = h.groupby(by)[["err_m", "err_b", "actual_units"]].sum()
    return pd.DataFrame({"wape_model": g.err_m / g.actual_units, "wape_baseline": g.err_b / g.actual_units}).round(4)


print("by horizon_week"); print(table("horizon_week").to_string())
print("\nby category"); print(table("category_id").to_string())
print("\nby is_critical"); print(table("is_critical").to_string())

# COMMAND ----------
# MAGIC %md ## 3. Unity Catalog registry: versions, alias, run linkage

# COMMAND ----------
mlflow.set_registry_uri("databricks-uc")
c = mlflow.MlflowClient()
rm = c.get_registered_model(MODEL)
print("model:", rm.name, "| aliases:", rm.aliases)
print("tags:", rm.tags)
champion = c.get_model_version_by_alias(MODEL, "champion")
print(f"@champion -> version {champion.version}, run_id {champion.run_id}")
for v in sorted(c.search_model_versions(f"name='{MODEL}'"), key=lambda v: int(v.version)):
    mv = c.get_model_version(MODEL, v.version)   # search rows expose aliases/tags as methods in UC
    print(f"  v{mv.version} aliases={mv.aliases} run_id={mv.run_id} tags={mv.tags}")
run = c.get_run(champion.run_id)
print("params :", dict(run.data.params))
print("metrics:", {k: round(v, 4) for k, v in run.data.metrics.items() if k in ("wape", "baseline_wape", "bias", "lift_vs_baseline")})
assert str(champion.version) == str(champ.model_version) and champion.run_id == champ.run_id

# COMMAND ----------
# MAGIC %md ## 4. Reproducibility and shape of the scored tables

# COMMAND ----------
fw = spark.table(f"{P}.aftersales_forecast_weekly").toPandas()
rk = spark.table(f"{P}.aftersales_stockout_risk").toPandas()
print("forecast_weekly rows:", len(fw), "| per series:", fw.groupby(["dealer_id", "part_id"]).size().unique())
print("model_version(s):", fw.model_version.unique(), rk.model_version.unique())
print("future weeks:", fw[fw.is_future].week_start.min(), "..", fw[fw.is_future].week_start.max())
print("stockout_risk rows:", len(rk), "| horizons:", sorted(rk.horizon_days.unique()))
print(rk.groupby(["horizon_days", "risk_level"]).size().unstack(fill_value=0).to_string())
print(rk.groupby(["horizon_days", "action"]).size().unstack(fill_value=0).to_string())
assert len(fw) == 720 * 34 and len(rk) == 720 * 3 and fw.model_version.nunique() == 1

# COMMAND ----------
# MAGIC %md ## 5. Samples

# COMMAND ----------
top = rk[rk.horizon_days == 28].sort_values(["lost_sales_brl", "stockout_probability"], ascending=False).head(8)
print(top[["dealer_id", "part_id", "stock_units", "on_order_units", "forecast_units", "days_to_stockout", "stockout_probability",
           "risk_level", "shortfall_units", "lost_sales_brl", "action", "recommended_qty", "transfer_from_dealer_id"]].round(3).to_string(index=False))
d, p = top.iloc[0].dealer_id, top.iloc[0].part_id
print(f"\nforecast series for {d} / {p}")
print(fw[(fw.dealer_id == d) & (fw.part_id == p)].sort_values("week_start")
      [["week_start", "is_future", "horizon_week", "actual_units", "forecast_units", "lower_units", "upper_units", "baseline_units"]]
      .tail(24).round(2).to_string(index=False))

# COMMAND ----------
text = sys.stdout.getvalue()
sys.stdout = sys.__stdout__
dbutils.notebook.exit(text)   # `databricks jobs get-run-output <task_run_id>` returns this text
