-- q1 Aurora share automoveis last 12 months
SELECT ref_month, round(100 * share, 2) AS share_pct, units FROM classic_stable.auto_intelligence.market_share_with_aurora WHERE is_synthetic AND segment = 'automoveis' AND ref_month > add_months((SELECT max(ref_month) FROM classic_stable.auto_intelligence.market_share_with_aurora), -12) ORDER BY ref_month;
-- q2 top 10 brands sep/2026 total market real
SELECT brand, sum(units) AS units FROM classic_stable.auto_intelligence.market_share_real WHERE ref_month = DATE'2026-09-01' AND NOT is_residual GROUP BY brand ORDER BY units DESC LIMIT 10;
-- q3 comerciais leves yearly 2019-2026
SELECT year(ref_month) AS ano, sum(units) AS units FROM classic_stable.auto_intelligence.market_segment_totals WHERE segment = 'comerciais_leves' AND year(ref_month) BETWEEN 2019 AND 2026 GROUP BY 1 ORDER BY 1;
-- q4 Aurora models 2025
SELECT model, sum(units) AS units FROM classic_stable.auto_intelligence.market_model_monthly WHERE is_synthetic AND year(ref_month) = 2025 GROUP BY model ORDER BY units DESC;
-- q5 brand growth automoveis jan-sep 2026 vs 2025
WITH y AS (SELECT brand, sum(CASE WHEN year(ref_month)=2026 THEN units END) AS u26, sum(CASE WHEN year(ref_month)=2025 THEN units END) AS u25 FROM classic_stable.auto_intelligence.market_share_real WHERE segment='automoveis' AND NOT is_residual AND month(ref_month) <= 9 AND year(ref_month) IN (2025,2026) GROUP BY brand) SELECT brand, u25, u26, u26 - u25 AS growth_units, round(100*(u26-u25)/u25,1) AS growth_pct FROM y WHERE u25 > 0 AND u26 IS NOT NULL ORDER BY growth_units DESC LIMIT 10;
