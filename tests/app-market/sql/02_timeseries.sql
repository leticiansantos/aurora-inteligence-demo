-- Oracle for GET /api/market/timeseries over [:from, :to].
-- Params: :from DATE, :to DATE, :segment STRING, :view STRING
WITH real AS (
  SELECT ref_month, sum(units) AS real_units
  FROM classic_stable.auto_intelligence.market_segment_totals
  WHERE ref_month BETWEEN :from AND :to AND (:segment = 'total' OR segment = :segment)
  GROUP BY ref_month
), aur AS (
  SELECT ref_month, sum(units) AS aurora_units
  FROM classic_stable.auto_intelligence.market_brand_monthly
  WHERE is_synthetic AND :view = 'with_aurora'
    AND ref_month BETWEEN :from AND :to AND (:segment = 'total' OR segment = :segment)
  GROUP BY ref_month
)
SELECT r.ref_month AS month, r.real_units, a.aurora_units,
       r.real_units + coalesce(a.aurora_units, 0) AS total_units,
       a.aurora_units / (r.real_units + coalesce(a.aurora_units, 0)) AS aurora_share
FROM real r LEFT JOIN aur a USING (ref_month)
ORDER BY month
