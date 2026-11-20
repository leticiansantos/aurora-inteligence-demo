-- Oracle for GET /api/market/models at :month (all published models, before limit).
-- Denominator = segment total of the view (published real + Aurora when with_aurora).
-- Params: :month DATE, :segment STRING, :view STRING
WITH tot AS (
  SELECT sum(units) + CASE WHEN :view = 'with_aurora' THEN coalesce((
           SELECT sum(units) FROM classic_stable.auto_intelligence.market_brand_monthly
           WHERE is_synthetic AND ref_month = :month AND (:segment = 'total' OR segment = :segment)), 0)
         ELSE 0 END AS total_units
  FROM classic_stable.auto_intelligence.market_segment_totals
  WHERE ref_month = :month AND (:segment = 'total' OR segment = :segment)
), m AS (
  SELECT brand, model, is_synthetic, sum(units) AS units, count(*) AS segment_rows
  FROM classic_stable.auto_intelligence.market_model_monthly
  WHERE ref_month = :month AND (:segment = 'total' OR segment = :segment)
    AND (:view = 'with_aurora' OR NOT is_synthetic)
  GROUP BY brand, model, is_synthetic
)
SELECT row_number() OVER (ORDER BY units DESC, brand, model) AS row_num, brand, model, units,
       units / tot.total_units AS share, is_synthetic, segment_rows,
       sum(units) OVER () AS covered_units, tot.total_units
FROM m CROSS JOIN tot
ORDER BY units DESC, brand, model
