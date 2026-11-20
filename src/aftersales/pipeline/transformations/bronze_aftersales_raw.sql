-- Raw layer: Auto Loader over the synthetic CSVs that the generator job task writes to the landing Volume.
-- All CSV columns stay STRING (typing happens in silver). The generator overwrites files with fixed names,
-- and Auto Loader ignores a rewritten file with the same name (default behaviour), so a rerun with the same generator_version ingests nothing new.
-- A generator_version change needs a FULL REFRESH of this pipeline (see ../README.md).

CREATE OR REFRESH STREAMING TABLE aftersales_raw_dealers
COMMENT 'Raw synthetic Aurora Motors dealers CSV (all columns STRING). Synthetic data, fictional dealers.'
AS SELECT
  *,
  _metadata.file_path AS _source_file,
  current_timestamp() AS _ingested_at
FROM STREAM read_files(
  '${aftersales.landing_path}dealers/',
  format => 'csv',
  header => 'true',
  schema => 'dealer_id STRING, dealer_name STRING, city STRING, state STRING, region STRING, opened_on STRING, fleet_share STRING'
);

CREATE OR REFRESH STREAMING TABLE aftersales_raw_parts
COMMENT 'Raw synthetic generic parts catalog CSV (all columns STRING). Synthetic data, no real brands or part codes.'
AS SELECT
  *,
  _metadata.file_path AS _source_file,
  current_timestamp() AS _ingested_at
FROM STREAM read_files(
  '${aftersales.landing_path}parts/',
  format => 'csv',
  header => 'true',
  schema => 'part_id STRING, part_name STRING, category_id STRING, category_name STRING, unit_price_brl STRING, unit_cost_brl STRING, is_critical STRING'
);

CREATE OR REFRESH STREAMING TABLE aftersales_raw_lead_times
COMMENT 'Raw synthetic supplier lead times per dealer and part CSV (all columns STRING). Synthetic data.'
AS SELECT
  *,
  _metadata.file_path AS _source_file,
  current_timestamp() AS _ingested_at
FROM STREAM read_files(
  '${aftersales.landing_path}lead_times/',
  format => 'csv',
  header => 'true',
  schema => 'dealer_id STRING, part_id STRING, lead_time_days STRING'
);

CREATE OR REFRESH STREAMING TABLE aftersales_raw_daily_sales
COMMENT 'Raw synthetic daily demand, sales and lost sales per dealer and part, one CSV per month (all columns STRING). Synthetic data.'
AS SELECT
  *,
  _metadata.file_path AS _source_file,
  current_timestamp() AS _ingested_at
FROM STREAM read_files(
  '${aftersales.landing_path}daily_sales/',
  format => 'csv',
  header => 'true',
  schema => 'sale_date STRING, dealer_id STRING, part_id STRING, demand_units STRING, sold_units STRING, lost_units STRING'
);

CREATE OR REFRESH STREAMING TABLE aftersales_raw_stock_snapshots
COMMENT 'Raw synthetic weekly (Sunday) stock snapshots per dealer and part, one CSV per month (all columns STRING). Synthetic data.'
AS SELECT
  *,
  _metadata.file_path AS _source_file,
  current_timestamp() AS _ingested_at
FROM STREAM read_files(
  '${aftersales.landing_path}stock_snapshots/',
  format => 'csv',
  header => 'true',
  schema => 'snapshot_date STRING, dealer_id STRING, part_id STRING, on_hand_units STRING, on_order_units STRING'
);
