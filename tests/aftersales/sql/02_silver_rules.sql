-- Silver rules (docs/data-model/aftersales.md §4 Silver)
WITH d AS (SELECT * FROM __T__aftersales_dealers), p AS (SELECT * FROM __T__aftersales_parts),
s AS (SELECT * FROM __T__aftersales_daily_sales)
SELECT 'dealers: 12 rows, ids D001..D012' AS check, count(*) = 12 AND min(dealer_id) = 'D001' AND max(dealer_id) = 'D012' AS ok, concat('n=', count(*)) AS detail FROM d
UNION ALL SELECT 'dealers: >=2 per region, 4 regions', min(n) >= 2 AND count(*) = 4 AND count_if(region NOT IN ('Sudeste','Sul','Nordeste','Centro-Oeste')) = 0, to_json(collect_list(struct(region, n))) FROM (SELECT region, count(*) n FROM d GROUP BY region)
UNION ALL SELECT 'dealers: sum(fleet_share) = 1', abs(sum(fleet_share) - 1) < 1e-9 AND min(fleet_share) > 0, cast(sum(fleet_share) AS STRING) FROM d
UNION ALL SELECT 'dealers: name "Aurora Motors <Cidade>", UF 2 letters', count_if(NOT dealer_name RLIKE '^Aurora Motors .+' OR NOT state RLIKE '^[A-Z]{2}$') = 0, concat('bad=', count_if(NOT dealer_name RLIKE '^Aurora Motors .+')) FROM d
UNION ALL SELECT 'parts: 60 rows P001..P060', count(*) = 60 AND min(part_id) = 'P001' AND max(part_id) = 'P060', concat('n=', count(*)) FROM p
UNION ALL SELECT 'parts: 0 < cost < price', count_if(NOT (unit_cost_brl > 0 AND unit_cost_brl < unit_price_brl)) = 0, concat('bad=', count_if(NOT (unit_cost_brl > 0 AND unit_cost_brl < unit_price_brl))) FROM p
UNION ALL SELECT 'parts: 8 categories from the contract list', count(DISTINCT category_id) = 8 AND count_if(category_id NOT IN ('brakes','filters','suspension','electrical','engine','cooling','lighting','air_conditioning')) = 0, to_json(collect_set(category_id)) FROM p
UNION ALL SELECT 'parts: category_id -> category_name 1:1', max(n) = 1, '' FROM (SELECT category_id, count(DISTINCT category_name) n FROM p GROUP BY 1)
UNION ALL SELECT 'parts: names unique, no digits-only codes', count(DISTINCT part_name) = count(*) AND count_if(part_name RLIKE '[0-9]{4,}') = 0, '' FROM p
UNION ALL SELECT 'lead_times: 720 rows, 3..30 days', count(*) = 720 AND min(lead_time_days) >= 3 AND max(lead_time_days) <= 30, concat(count(*), ' rows, ', min(lead_time_days), '..', max(lead_time_days)) FROM __T__aftersales_lead_times
UNION ALL SELECT 'daily_sales: range 2019-01-01..2026-11-15', min(sale_date) = DATE'2019-01-01' AND max(sale_date) = DATE'2026-11-15', concat(min(sale_date), '..', max(sale_date)) FROM s
UNION ALL SELECT 'daily_sales: dense grid 720 x days', count(*) = 720 * (datediff(DATE'2026-11-15', DATE'2019-01-01') + 1), concat(count(*), ' vs ', 720 * (datediff(DATE'2026-11-15', DATE'2019-01-01') + 1)) FROM s
UNION ALL SELECT 'daily_sales: lost = demand - sold >= 0, sold >= 0', count_if(lost_units <> demand_units - sold_units OR lost_units < 0 OR sold_units < 0) = 0, concat('bad=', count_if(lost_units <> demand_units - sold_units OR lost_units < 0 OR sold_units < 0)) FROM s
UNION ALL SELECT 'daily_sales: Sunday demand = 0', count_if(dayofweek(sale_date) = 1 AND demand_units <> 0) = 0, concat('bad=', count_if(dayofweek(sale_date) = 1 AND demand_units <> 0)) FROM s
UNION ALL SELECT 'stock_snapshots: Sundays only, >= 0', count_if(dayofweek(snapshot_date) <> 1 OR on_hand_units < 0 OR on_order_units < 0) = 0 AND max(snapshot_date) = DATE'2026-11-15', concat('max=', max(snapshot_date), ' bad=', count_if(dayofweek(snapshot_date) <> 1 OR on_hand_units < 0 OR on_order_units < 0)) FROM __T__aftersales_stock_snapshots
UNION ALL SELECT 'stock_snapshots: every Sunday has 720 rows', min(n) = 720 AND max(n) = 720, concat(count(*), ' sundays, ', min(n), '..', max(n)) FROM (SELECT snapshot_date, count(*) n FROM __T__aftersales_stock_snapshots GROUP BY 1)
