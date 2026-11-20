# Aftersales SDP pipeline

Lakeflow Spark Declarative Pipeline `aftersales_pipeline` (`resources/aftersales_pipeline.yml`). All data is synthetic.
Contract: `docs/data-model/aftersales.md` (sections 3 and 4). Decisions: `docs/architecture/aftersales.md` (D7, D9).

## Layers (`transformations/`)

- **Raw** (`bronze_aftersales_raw.sql`): five streaming tables `aftersales_raw_*`, loaded with Auto Loader
  (`read_files`) from `${aftersales.landing_path}<entity>/`. CSV columns are kept as STRING, plus `_source_file`
  and `_ingested_at`.
- **Silver** (`silver_aftersales_dimensions.sql`, `silver_aftersales_facts.sql`): typed materialized views
  `aftersales_dealers`, `aftersales_parts`, `aftersales_lead_times`, `aftersales_daily_sales`,
  `aftersales_stock_snapshots` and `aftersales_fleet_monthly`. The fleet is
  `market_synthetic_registrations.units x dealers.fleet_share`, accumulated per dealer and model. That table comes
  from `market_pipeline` and is read by its unqualified name (same catalog and schema).
- **Gold** (`gold_aftersales.sql`): `aftersales_demand_weekly` (Monday-start full weeks, 2019-01-07 to 2026-11-09)
  and `aftersales_stock_position` (latest snapshot per dealer and part, 720 rows).

Data-quality rules are `CONSTRAINT ... EXPECT`. Only null primary-key rows are dropped; every other rule is warn-only.
UC tags (`synthetic`, `aid_domain` (the key `domain` is governed in this account), `layer`) are not applied by SDP; the `govern` job task sets them.

## Full refresh rule

The generator overwrites files with fixed names and the Auto Loader ignores rewritten files
(default `allowOverwrites` = false). So a rerun with the same `seed` and `generator_version` adds no rows.
**When `generator_version` (or `seed`) changes, run the pipeline with a full refresh** so the raw tables are
reloaded from the new files; otherwise the old rows stay and the new files are skipped.

## Serverless rules (from ADR 001)

No `spark.catalog` or Spark actions inside dataset definitions, UDFs only from by-value modules, and no private
materialized views.

## Shape of lost sales (generator behavior)

Lost sales are episodic by design: ~10% of supplier orders are delayed (lead time x2.2), and a delay that outlasts the
reorder buffer starves fast movers at the larger dealers for a few weeks (e.g. 2020-03/04, 2026-03/04). On top of that,
a documented disruption (filters, engine and lighting orders placed 2026-08-15..2026-10-31 arrive 45 days late) drives
the Sep/Oct 2026 spike so the last 4 weeks show real stockouts. Yearly lost share is therefore low (0.3-0.9% in
2021-2025) with occasional episodes; it is not a drifting policy.
