-- Silver dimensions: typed and validated copies of the synthetic raw CSVs.

CREATE OR REFRESH MATERIALIZED VIEW aftersales_dealers (
  dealer_id STRING COMMENT 'Synthetic dealer id, D001..D012 (primary key)',
  dealer_name STRING COMMENT 'Fictional dealer name, format "Aurora Motors <City>"',
  city STRING COMMENT 'Dealer city (real Brazilian city, fictional dealer)',
  state STRING COMMENT 'Brazilian state code (UF)',
  region STRING COMMENT 'Region: Sudeste, Sul, Nordeste or Centro-Oeste',
  opened_on DATE COMMENT 'Synthetic opening date',
  fleet_share DOUBLE COMMENT 'Synthetic share of the Aurora fleet served by this dealer; sums to 1 across dealers',
  CONSTRAINT dealer_id_not_null EXPECT (dealer_id IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT fleet_share_valid EXPECT (fleet_share > 0 AND fleet_share <= 1),
  CONSTRAINT region_valid EXPECT (region IN ('Sudeste', 'Sul', 'Nordeste', 'Centro-Oeste'))
)
COMMENT 'Synthetic Aurora Motors dealers (12 fictional stores). Silver, typed from aftersales_raw_dealers.'
AS SELECT
  dealer_id,
  dealer_name,
  city,
  state,
  region,
  try_cast(opened_on AS DATE) AS opened_on,
  try_cast(fleet_share AS DOUBLE) AS fleet_share
FROM aftersales_raw_dealers;

CREATE OR REFRESH MATERIALIZED VIEW aftersales_parts (
  part_id STRING COMMENT 'Synthetic part id, P001..P060 (primary key)',
  part_name STRING COMMENT 'Generic part name in pt-BR (no real brand or code)',
  category_id STRING COMMENT 'Category slug: brakes, filters, suspension, electrical, engine, cooling, lighting, air_conditioning',
  category_name STRING COMMENT 'Category name in pt-BR',
  unit_price_brl DOUBLE COMMENT 'Synthetic unit sale price in BRL',
  unit_cost_brl DOUBLE COMMENT 'Synthetic unit cost in BRL; always below the unit price',
  is_critical BOOLEAN COMMENT 'True when a missing part immobilizes the vehicle',
  CONSTRAINT part_id_not_null EXPECT (part_id IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT cost_below_price EXPECT (unit_cost_brl > 0 AND unit_cost_brl < unit_price_brl)
)
COMMENT 'Synthetic generic parts catalog (60 parts, no real brands or codes). Silver, typed from aftersales_raw_parts.'
AS SELECT
  part_id,
  part_name,
  category_id,
  category_name,
  try_cast(unit_price_brl AS DOUBLE) AS unit_price_brl,
  try_cast(unit_cost_brl AS DOUBLE) AS unit_cost_brl,
  lower(trim(is_critical)) IN ('true', 't', '1', 'yes') AS is_critical
FROM aftersales_raw_parts;

CREATE OR REFRESH MATERIALIZED VIEW aftersales_lead_times (
  dealer_id STRING COMMENT 'Synthetic dealer id (primary key part 1)',
  part_id STRING COMMENT 'Synthetic part id (primary key part 2)',
  lead_time_days INT COMMENT 'Synthetic supplier lead time in days, between 3 and 30',
  CONSTRAINT keys_not_null EXPECT (dealer_id IS NOT NULL AND part_id IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT lead_time_range EXPECT (lead_time_days BETWEEN 3 AND 30)
)
COMMENT 'Synthetic supplier lead time per dealer and part (12 x 60 = 720 rows). Silver, typed from aftersales_raw_lead_times.'
AS SELECT
  dealer_id,
  part_id,
  try_cast(lead_time_days AS INT) AS lead_time_days
FROM aftersales_raw_lead_times;
