-- forecast_weekly structure + backtest honesty + WAPE recomputation (data model §4 ML)
WITH f AS (SELECT * FROM __T__aftersales_forecast_weekly),
dw AS (SELECT * FROM __T__aftersales_demand_weekly),
champ AS (SELECT * FROM __T__aftersales_model_metrics WHERE is_champion),
ho AS (SELECT * FROM f WHERE NOT is_future AND forecast_units IS NOT NULL)
SELECT 'forecast: 34 rows per series (26 history + 8 future)' AS check, min(n) = 34 AND max(n) = 34 AND count(*) = 720 AS ok, concat(count(*), ' series ', min(n), '..', max(n)) AS detail
FROM (SELECT dealer_id, part_id, count(*) n FROM f GROUP BY ALL)
UNION ALL SELECT 'forecast: history weeks 2026-05-18..2026-11-09, future 2026-11-16..2027-01-04',
  min(week_start) FILTER (WHERE NOT is_future) = DATE'2026-05-18' AND max(week_start) FILTER (WHERE NOT is_future) = DATE'2026-11-09'
  AND min(week_start) FILTER (WHERE is_future) = DATE'2026-11-16' AND max(week_start) FILTER (WHERE is_future) = DATE'2027-01-04'
  AND count_if(dayofweek(week_start) <> 2) = 0, '' FROM f
UNION ALL SELECT 'forecast: holdout = last 13 history weeks (after cutoff 2026-08-16), horizon_week 1..13',
  count(*) = 720 * 13 AND min(week_start) = DATE'2026-08-17' AND min(horizon_week) = 1 AND max(horizon_week) = 13
  AND count_if(horizon_week <> (datediff(week_start, DATE'2026-08-17') / 7) + 1) = 0, concat('rows=', count(*), ' min_week=', min(week_start)) FROM ho
UNION ALL SELECT 'forecast: pre-holdout history has null forecast/interval/baseline',
  count_if(forecast_units IS NOT NULL OR lower_units IS NOT NULL OR upper_units IS NOT NULL OR baseline_units IS NOT NULL) = 0 AND count(*) = 720 * 13, concat('rows=', count(*)) FROM f WHERE NOT is_future AND week_start < DATE'2026-08-17'
UNION ALL SELECT 'forecast: future rows have no actual/sold/baseline, horizon_week 1..8',
  count_if(actual_units IS NOT NULL OR sold_units IS NOT NULL OR baseline_units IS NOT NULL OR forecast_units IS NULL) = 0 AND min(horizon_week) = 1 AND max(horizon_week) = 8, '' FROM f WHERE is_future
UNION ALL SELECT 'forecast: history actual/sold == demand_weekly demand/sold',
  count_if(dw.week_start IS NULL OR f.actual_units <> dw.demand_units OR f.sold_units <> dw.sold_units) = 0, concat('bad=', count_if(dw.week_start IS NULL OR f.actual_units <> dw.demand_units OR f.sold_units <> dw.sold_units))
  FROM f LEFT JOIN dw USING (week_start, dealer_id, part_id) WHERE NOT f.is_future
UNION ALL SELECT 'forecast: 0 <= lower <= forecast <= upper, forecast >= 0',
  count_if(NOT (lower_units >= 0 AND lower_units <= forecast_units + 1e-9 AND forecast_units <= upper_units + 1e-9)) = 0, concat('bad=', count_if(NOT (lower_units >= 0 AND lower_units <= forecast_units + 1e-9 AND forecast_units <= upper_units + 1e-9))) FROM f WHERE forecast_units IS NOT NULL
UNION ALL SELECT 'forecast: interval = max(0, f +/- 1.2816 * max(holdout RMSE, 0.5))',
  count_if(abs(f.upper_units - (f.forecast_units + 1.2816 * r.sigma)) > 1e-4 OR abs(f.lower_units - greatest(0, f.forecast_units - 1.2816 * r.sigma)) > 1e-4) = 0,
  concat('bad=', count_if(abs(f.upper_units - (f.forecast_units + 1.2816 * r.sigma)) > 1e-4 OR abs(f.lower_units - greatest(0, f.forecast_units - 1.2816 * r.sigma)) > 1e-4))
  FROM f JOIN (SELECT dealer_id, part_id, greatest(sqrt(avg(pow(actual_units - forecast_units, 2))), 0.5) sigma FROM ho GROUP BY ALL) r USING (dealer_id, part_id) WHERE f.forecast_units IS NOT NULL
UNION ALL SELECT 'forecast: baseline = seasonal naive (value 52 weeks earlier)',
  count_if(dw.week_start IS NULL OR abs(ho.baseline_units - dw.demand_units) > 1e-9) = 0, concat('bad=', count_if(dw.week_start IS NULL OR abs(ho.baseline_units - dw.demand_units) > 1e-9), ' (REPORT: confirm baseline rule with ADR D4)')
  FROM ho LEFT JOIN dw ON dw.dealer_id = ho.dealer_id AND dw.part_id = ho.part_id AND dw.week_start = date_sub(ho.week_start, 364)
UNION ALL SELECT 'metrics: exactly one champion, forecast_date 2026-11-16, cutoff 2026-08-16, 13 holdout weeks, 720 series',
  (SELECT count(*) FROM champ) = 1 AND max(forecast_date) = DATE'2026-11-16' AND max(cutoff_date) = DATE'2026-08-16' AND max(holdout_weeks) = 13 AND max(n_series) = 720, to_json(collect_list(struct(model_version, wape, baseline_wape))) FROM champ
UNION ALL SELECT 'metrics: champion WAPE recomputed from holdout rows',
  abs((SELECT wape FROM champ) - sum(abs(actual_units - forecast_units)) / sum(actual_units)) < 1e-6, concat('recomputed=', round(sum(abs(actual_units - forecast_units)) / sum(actual_units), 6), ' table=', (SELECT round(wape, 6) FROM champ)) FROM ho
UNION ALL SELECT 'metrics: champion baseline WAPE recomputed',
  abs((SELECT baseline_wape FROM champ) - sum(abs(actual_units - baseline_units)) / sum(actual_units)) < 1e-6, concat('recomputed=', round(sum(abs(actual_units - baseline_units)) / sum(actual_units), 6)) FROM ho
UNION ALL SELECT 'metrics: champion bias recomputed', abs((SELECT bias FROM champ) - sum(forecast_units - actual_units) / sum(actual_units)) < 1e-6, concat('recomputed=', round(sum(forecast_units - actual_units) / sum(actual_units), 6)) FROM ho
UNION ALL SELECT 'metrics: model beats seasonal-naive baseline', (SELECT wape < baseline_wape FROM champ), (SELECT concat('wape=', round(wape, 4), ' baseline=', round(baseline_wape, 4)) FROM champ)
UNION ALL SELECT 'forecast: every row (holdout and future) carries the champion version N, one forecast_date', count(DISTINCT model_version) = 1 AND max(model_version) = (SELECT model_version FROM champ) AND count(DISTINCT forecast_date) = 1 AND max(forecast_date) = DATE'2026-11-16', to_json(collect_set(model_version)) FROM f
