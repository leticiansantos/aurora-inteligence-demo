-- Synthetic plausibility (REPORT-style: thresholds are QA judgement, documented in tests/aftersales/README.md)
WITH dw AS (SELECT * FROM __T__aftersales_demand_weekly),
yr AS (SELECT year(week_start) y, sum(demand_units) d, sum(lost_units) l, sum(sold_units) s FROM dw WHERE week_start < DATE'2026-01-05' GROUP BY 1),
fleet AS (SELECT year(ref_month) y, sum(active_fleet_units) / 12 f FROM __T__aftersales_fleet_monthly GROUP BY 1)
SELECT 'QA-judgement: yearly demand grows with the active fleet (corr > 0.8)' AS check, corr(yr.d, fleet.f) > 0.8 AS ok, concat('corr=', round(corr(yr.d, fleet.f), 3), ' ', to_json(collect_list(struct(yr.y, yr.d)))) AS detail FROM yr JOIN fleet USING (y)
UNION ALL SELECT 'D1 target: fill rate of the last 4 weeks (2026-10-19..11-15) between 0.88 and 0.97', sum(sold_units) / sum(demand_units) BETWEEN 0.88 AND 0.97, concat('fill=', round(sum(sold_units) / sum(demand_units), 4)) FROM dw WHERE week_start BETWEEN DATE'2026-10-19' AND DATE'2026-11-09'
UNION ALL SELECT 'QA-judgement: last-year lost sales between 1% and 20% of demand', sum(l) / sum(d) BETWEEN 0.01 AND 0.20, concat('lost_share=', round(sum(l) / sum(d), 4)) FROM yr WHERE y = 2025
UNION ALL SELECT 'QA-judgement: seasonality present (max/min monthly index of 2023-2025 >= 1.10)', max(idx) / min(idx) >= 1.10, concat('ratio=', round(max(idx) / min(idx), 3))
  FROM (SELECT month(week_start) m, sum(demand_units) / avg(sum(demand_units)) OVER () idx FROM dw WHERE year(week_start) BETWEEN 2023 AND 2025 GROUP BY 1)
UNION ALL SELECT 'QA-judgement: not every series is identical (cv of series totals > 0.3)', stddev(t) / avg(t) > 0.3, concat('cv=', round(stddev(t) / avg(t), 3))
  FROM (SELECT dealer_id, part_id, sum(demand_units) t FROM dw GROUP BY ALL)
UNION ALL SELECT 'QA-judgement: < 20% of series have zero demand in the last 26 weeks', count_if(t = 0) / count(*) < 0.2, concat('zero_series=', count_if(t = 0))
  FROM (SELECT dealer_id, part_id, sum(demand_units) t FROM dw WHERE week_start >= DATE'2026-05-18' GROUP BY ALL)
UNION ALL SELECT 'QA-judgement: current stock spread (some at risk, some surplus)', count_if(on_hand_units = 0) BETWEEN 1 AND 360 AND count_if(on_hand_units > 0) > 360, concat('zero_stock=', count_if(on_hand_units = 0), ' of ', count(*)) FROM __T__aftersales_stock_position
UNION ALL SELECT 'QA-judgement: prices in a sane BRL range (5..10000), margin 10%..70%', min(unit_price_brl) >= 5 AND max(unit_price_brl) <= 10000 AND min(1 - unit_cost_brl / unit_price_brl) >= 0.10 AND max(1 - unit_cost_brl / unit_price_brl) <= 0.70,
  concat('price ', round(min(unit_price_brl), 2), '..', round(max(unit_price_brl), 2), ' margin ', round(min(1 - unit_cost_brl / unit_price_brl), 3), '..', round(max(1 - unit_cost_brl / unit_price_brl), 3)) FROM __T__aftersales_parts
UNION ALL SELECT 'QA-judgement: no demand before dealer opened_on', count_if(s.sale_date < d.opened_on AND s.demand_units > 0) = 0, concat('bad=', count_if(s.sale_date < d.opened_on AND s.demand_units > 0)) FROM __T__aftersales_daily_sales s JOIN __T__aftersales_dealers d USING (dealer_id)
