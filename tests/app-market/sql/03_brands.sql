-- Oracle for GET /api/market/brands: full (un-limited) list summed over [:from, :to].
-- latestMonth list: :from = :to = latest month. period list: the period window.
-- Params: :from DATE, :to DATE, :segment STRING, :view STRING
WITH b AS (
  SELECT brand, is_residual, is_synthetic, sum(units) AS units
  FROM classic_stable.auto_intelligence.market_brand_monthly
  WHERE ref_month BETWEEN :from AND :to
    AND (:segment = 'total' OR segment = :segment)
    AND (:view = 'with_aurora' OR NOT is_synthetic)
  GROUP BY brand, is_residual, is_synthetic
)
SELECT CASE WHEN is_residual THEN NULL
            ELSE dense_rank() OVER (PARTITION BY is_residual ORDER BY units DESC) END AS dense_rnk,
       CASE WHEN is_residual THEN NULL
            ELSE row_number() OVER (PARTITION BY is_residual ORDER BY units DESC, brand) END AS row_num,
       brand, units, units / sum(units) OVER () AS share, sum(units) OVER () AS total_units,
       is_synthetic, is_residual
FROM b
ORDER BY is_residual, units DESC, brand
