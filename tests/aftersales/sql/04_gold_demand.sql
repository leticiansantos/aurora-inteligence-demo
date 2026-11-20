-- demand_weekly re-aggregated from daily_sales + parts + fleet (data model §4 Gold)
WITH w AS (
  SELECT date_trunc('week', s.sale_date)::date AS week_start, s.dealer_id, s.part_id,
         sum(demand_units) demand, sum(sold_units) sold, sum(lost_units) lost
  FROM __T__aftersales_daily_sales s GROUP BY ALL),
fl AS (SELECT dealer_id, ref_month, sum(active_fleet_units) fleet FROM __T__aftersales_fleet_monthly GROUP BY ALL),
o AS (
  SELECT w.*, w.lost * p.unit_price_brl AS lost_brl, CASE WHEN w.demand = 0 THEN NULL ELSE w.sold / w.demand END AS fr, fl.fleet
  FROM w JOIN __T__aftersales_parts p USING (part_id)
  LEFT JOIN fl ON fl.dealer_id = w.dealer_id AND fl.ref_month = least(date_trunc('month', w.week_start)::date, DATE'2026-09-01')
  WHERE w.week_start BETWEEN DATE'2019-01-07' AND DATE'2026-11-09'),
j AS (SELECT o.*, g.* EXCEPT (week_start, dealer_id, part_id), g.week_start AS g_week
      FROM o FULL OUTER JOIN __T__aftersales_demand_weekly g USING (week_start, dealer_id, part_id))
SELECT 'demand_weekly: same keys as weekly re-aggregation' AS check, count_if(g_week IS NULL OR demand IS NULL) = 0 AS ok,
       concat('only_oracle=', count_if(g_week IS NULL), ' only_gold=', count_if(demand IS NULL)) AS detail FROM j
UNION ALL SELECT 'demand_weekly: demand/sold/lost equal', count_if(demand <> demand_units OR sold <> sold_units OR lost <> lost_units) = 0, concat('bad=', count_if(demand <> demand_units OR sold <> sold_units OR lost <> lost_units)) FROM j WHERE g_week IS NOT NULL AND demand IS NOT NULL
UNION ALL SELECT 'demand_weekly: lost_sales_brl = lost x price', count_if(abs(lost_brl - lost_sales_brl) > 1e-6) = 0, concat('bad=', count_if(abs(lost_brl - lost_sales_brl) > 1e-6)) FROM j WHERE g_week IS NOT NULL AND demand IS NOT NULL
UNION ALL SELECT 'demand_weekly: fill_rate = sold/demand, null when demand 0', count_if(NOT ((fr IS NULL AND fill_rate IS NULL) OR abs(fr - fill_rate) < 1e-9)) = 0, concat('bad=', count_if(NOT ((fr IS NULL AND fill_rate IS NULL) OR abs(fr - fill_rate) < 1e-9))) FROM j WHERE g_week IS NOT NULL AND demand IS NOT NULL
UNION ALL SELECT 'demand_weekly: active_fleet_units = dealer fleet of week month (2026-09 frozen)', count_if(abs(fleet - active_fleet_units) > 1e-6 OR fleet IS NULL) = 0, concat('bad=', count_if(abs(fleet - active_fleet_units) > 1e-6 OR fleet IS NULL)) FROM j WHERE g_week IS NOT NULL AND demand IS NOT NULL
UNION ALL SELECT 'stock_position = latest snapshot + lead time', count_if(sp.dealer_id IS NULL OR x.dealer_id IS NULL OR sp.on_hand_units <> x.on_hand_units OR sp.on_order_units <> x.on_order_units OR sp.lead_time_days <> x.lead_time_days OR sp.snapshot_date <> x.snapshot_date) = 0,
       concat('bad=', count_if(sp.dealer_id IS NULL OR x.dealer_id IS NULL OR sp.on_hand_units <> x.on_hand_units OR sp.on_order_units <> x.on_order_units OR sp.lead_time_days <> x.lead_time_days OR sp.snapshot_date <> x.snapshot_date))
FROM __T__aftersales_stock_position sp FULL OUTER JOIN (
  SELECT s.*, l.lead_time_days FROM __T__aftersales_stock_snapshots s JOIN __T__aftersales_lead_times l USING (dealer_id, part_id)
  WHERE s.snapshot_date = (SELECT max(snapshot_date) FROM __T__aftersales_stock_snapshots)) x USING (dealer_id, part_id)
