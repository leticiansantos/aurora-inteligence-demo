-- Silver facts: typed daily sales and weekly stock snapshots, plus the monthly Aurora fleet per dealer.

CREATE OR REFRESH MATERIALIZED VIEW aftersales_daily_sales (
  sale_date DATE COMMENT 'Sale date (primary key part 1); Sundays have zero demand because stores are closed',
  dealer_id STRING COMMENT 'Synthetic dealer id (primary key part 2)',
  part_id STRING COMMENT 'Synthetic part id (primary key part 3)',
  demand_units INT COMMENT 'Synthetic units demanded that day',
  sold_units INT COMMENT 'Synthetic units sold that day (limited by stock)',
  lost_units INT COMMENT 'Synthetic units of unmet demand: demand_units - sold_units',
  CONSTRAINT keys_not_null EXPECT (sale_date IS NOT NULL AND dealer_id IS NOT NULL AND part_id IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT lost_is_demand_minus_sold EXPECT (lost_units = demand_units - sold_units AND lost_units >= 0),
  CONSTRAINT units_not_negative EXPECT (demand_units >= 0 AND sold_units >= 0)
)
COMMENT 'Synthetic daily demand, sales and lost sales per dealer and part (dense grid, 2019-01-01 to 2026-11-15). Silver, typed from aftersales_raw_daily_sales.'
AS SELECT
  try_cast(sale_date AS DATE) AS sale_date,
  dealer_id,
  part_id,
  try_cast(demand_units AS INT) AS demand_units,
  try_cast(sold_units AS INT) AS sold_units,
  try_cast(lost_units AS INT) AS lost_units
FROM aftersales_raw_daily_sales;

CREATE OR REFRESH MATERIALIZED VIEW aftersales_stock_snapshots (
  snapshot_date DATE COMMENT 'Snapshot date, always a Sunday (primary key part 1)',
  dealer_id STRING COMMENT 'Synthetic dealer id (primary key part 2)',
  part_id STRING COMMENT 'Synthetic part id (primary key part 3)',
  on_hand_units INT COMMENT 'Synthetic units on hand at the snapshot',
  on_order_units INT COMMENT 'Synthetic units on order (in transit) at the snapshot',
  CONSTRAINT keys_not_null EXPECT (snapshot_date IS NOT NULL AND dealer_id IS NOT NULL AND part_id IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT units_not_negative EXPECT (on_hand_units >= 0 AND on_order_units >= 0),
  CONSTRAINT snapshot_is_sunday EXPECT (dayofweek(snapshot_date) = 1)
)
COMMENT 'Synthetic weekly (Sunday) stock snapshots per dealer and part. Silver, typed from aftersales_raw_stock_snapshots.'
AS SELECT
  try_cast(snapshot_date AS DATE) AS snapshot_date,
  dealer_id,
  part_id,
  try_cast(on_hand_units AS INT) AS on_hand_units,
  try_cast(on_order_units AS INT) AS on_order_units
FROM aftersales_raw_stock_snapshots;

-- market_synthetic_registrations is published by market_pipeline into the same catalog/schema, so the
-- unqualified name resolves through this pipeline's default catalog and schema.
CREATE OR REFRESH MATERIALIZED VIEW aftersales_fleet_monthly (
  ref_month DATE COMMENT 'First day of the reference month, 2019-01 to 2026-09 (primary key part 1)',
  dealer_id STRING COMMENT 'Synthetic dealer id (primary key part 2)',
  model STRING COMMENT 'Synthetic Aurora Motors model: IPE, JATOBA or AROEIRA (primary key part 3)',
  registrations_units DOUBLE COMMENT 'Synthetic registrations of the month allocated to the dealer: market units x fleet_share (not rounded)',
  active_fleet_units DOUBLE COMMENT 'Synthetic active fleet: cumulative registrations_units per dealer and model up to ref_month (no scrapping)',
  CONSTRAINT keys_not_null EXPECT (ref_month IS NOT NULL AND dealer_id IS NOT NULL AND model IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT registrations_not_negative EXPECT (registrations_units >= 0)
)
COMMENT 'Synthetic monthly Aurora Motors fleet per dealer and model, derived from market_synthetic_registrations x aftersales_dealers.fleet_share. Fully synthetic.'
AS
WITH reg AS (
  SELECT ref_month, model, CAST(SUM(units) AS DOUBLE) AS units
  FROM market_synthetic_registrations
  GROUP BY ref_month, model
),
alloc AS (
  SELECT r.ref_month, d.dealer_id, r.model, r.units * d.fleet_share AS registrations_units
  FROM reg r
  CROSS JOIN aftersales_dealers d
)
SELECT
  ref_month,
  dealer_id,
  model,
  registrations_units,
  SUM(registrations_units) OVER (
    PARTITION BY dealer_id, model ORDER BY ref_month
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
  ) AS active_fleet_units
FROM alloc;
