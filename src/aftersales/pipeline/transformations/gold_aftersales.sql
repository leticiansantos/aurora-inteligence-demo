-- Gold: weekly demand per dealer and part (forecasting input) and the latest stock position.

CREATE OR REFRESH MATERIALIZED VIEW aftersales_demand_weekly (
  week_start DATE COMMENT 'Monday that starts the week (primary key part 1); full weeks only, 2019-01-07 to 2026-11-09',
  dealer_id STRING COMMENT 'Synthetic dealer id (primary key part 2)',
  part_id STRING COMMENT 'Synthetic part id (primary key part 3)',
  demand_units INT COMMENT 'Synthetic units demanded in the week',
  sold_units INT COMMENT 'Synthetic units sold in the week',
  lost_units INT COMMENT 'Synthetic units of unmet demand in the week',
  lost_sales_brl DOUBLE COMMENT 'Synthetic lost revenue in BRL: lost_units x unit_price_brl',
  fill_rate DOUBLE COMMENT 'sold_units / demand_units; null when demand is 0',
  active_fleet_units DOUBLE COMMENT 'Synthetic total active fleet of the dealer (all models) in the month of week_start; 2026-09 value is used for later months',
  CONSTRAINT keys_not_null EXPECT (week_start IS NOT NULL AND dealer_id IS NOT NULL AND part_id IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT lost_not_negative EXPECT (lost_units >= 0),
  CONSTRAINT fleet_present EXPECT (active_fleet_units IS NOT NULL),
  CONSTRAINT fill_rate_range EXPECT (fill_rate IS NULL OR (fill_rate >= 0 AND fill_rate <= 1))
)
COMMENT 'Synthetic weekly (Monday-Sunday) demand, sales and lost sales per dealer and part, with the dealer active fleet. Gold, input of the demand forecaster.'
AS
WITH weekly AS (
  SELECT
    CAST(date_trunc('week', sale_date) AS DATE) AS week_start,
    dealer_id,
    part_id,
    CAST(SUM(demand_units) AS INT) AS demand_units,
    CAST(SUM(sold_units) AS INT) AS sold_units,
    CAST(SUM(lost_units) AS INT) AS lost_units
  FROM aftersales_daily_sales
  GROUP BY CAST(date_trunc('week', sale_date) AS DATE), dealer_id, part_id
),
fleet AS (
  SELECT ref_month, dealer_id, SUM(active_fleet_units) AS active_fleet_units
  FROM aftersales_fleet_monthly
  GROUP BY ref_month, dealer_id
)
SELECT
  w.week_start,
  w.dealer_id,
  w.part_id,
  w.demand_units,
  w.sold_units,
  w.lost_units,
  CAST(w.lost_units AS DOUBLE) * p.unit_price_brl AS lost_sales_brl,
  CAST(w.sold_units AS DOUBLE) / NULLIF(w.demand_units, 0) AS fill_rate,
  f.active_fleet_units
FROM weekly w
LEFT JOIN aftersales_parts p ON p.part_id = w.part_id
LEFT JOIN fleet f
  ON f.dealer_id = w.dealer_id
 AND f.ref_month = LEAST(CAST(date_trunc('month', w.week_start) AS DATE), DATE'2026-09-01')
WHERE w.week_start BETWEEN DATE'2019-01-07' AND DATE'2026-11-09';

CREATE OR REFRESH MATERIALIZED VIEW aftersales_stock_position (
  dealer_id STRING COMMENT 'Synthetic dealer id (primary key part 1)',
  part_id STRING COMMENT 'Synthetic part id (primary key part 2)',
  snapshot_date DATE COMMENT 'Date of the latest stock snapshot (2026-11-15)',
  on_hand_units INT COMMENT 'Synthetic units on hand at the latest snapshot',
  on_order_units INT COMMENT 'Synthetic units on order at the latest snapshot',
  lead_time_days INT COMMENT 'Synthetic supplier lead time in days',
  CONSTRAINT keys_not_null EXPECT (dealer_id IS NOT NULL AND part_id IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT lead_time_present EXPECT (lead_time_days IS NOT NULL)
)
COMMENT 'Synthetic latest stock snapshot per dealer and part joined with lead times (720 rows). Gold, input of the stockout risk scoring.'
AS
WITH latest AS (
  SELECT
    dealer_id, part_id, snapshot_date, on_hand_units, on_order_units,
    row_number() OVER (PARTITION BY dealer_id, part_id ORDER BY snapshot_date DESC) AS rn
  FROM aftersales_stock_snapshots
)
SELECT
  s.dealer_id,
  s.part_id,
  s.snapshot_date,
  s.on_hand_units,
  s.on_order_units,
  l.lead_time_days
FROM latest s
LEFT JOIN aftersales_lead_times l ON l.dealer_id = s.dealer_id AND l.part_id = s.part_id
WHERE s.rn = 1;
