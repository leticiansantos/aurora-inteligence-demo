-- PKs of the ML tables (data model §4 ML)
SELECT 'forecast_weekly pk' AS check, count(*) = count(DISTINCT dealer_id, part_id, week_start) AND count(*) = 24480 AS ok, concat('rows=', count(*)) AS detail FROM __T__aftersales_forecast_weekly
UNION ALL SELECT 'model_metrics pk', count(*) = count(DISTINCT model_version) AND count(*) >= 1, concat('rows=', count(*)) FROM __T__aftersales_model_metrics
UNION ALL SELECT 'stockout_risk pk', count(*) = count(DISTINCT dealer_id, part_id, horizon_days) AND count(*) = 2160, concat('rows=', count(*)) FROM __T__aftersales_stockout_risk
UNION ALL SELECT 'referential: every risk part exists', (SELECT count(*) FROM __T__aftersales_stockout_risk r LEFT ANTI JOIN __T__aftersales_parts p USING (part_id)) = 0, 'orphans in daily_sales/stockout_risk'
