-- Share is a fraction (0.03 = 3%). Denominator = published segment total (never sum of rows).
-- rank = dense_rank by units among non-residual rows; residual rows have NULL rank.
CREATE OR REFRESH MATERIALIZED VIEW market_share_real
COMMENT 'Real market share per brand and segment (no synthetic rows)'
AS
WITH base AS (
  SELECT b.ref_month, b.segment, b.brand, b.units, t.units AS segment_total_units, b.is_synthetic, b.is_residual
  FROM market_brand_monthly b
  JOIN market_segment_totals t ON t.ref_month = b.ref_month AND t.segment = b.segment
  WHERE NOT b.is_synthetic
)
SELECT ref_month, segment, brand, units, segment_total_units,
       CAST(units AS DOUBLE) / NULLIF(segment_total_units, 0) AS share,
       CASE WHEN is_residual THEN CAST(NULL AS INT)
            ELSE CAST(dense_rank() OVER (PARTITION BY ref_month, segment, is_residual ORDER BY units DESC) AS INT) END AS rank,
       is_synthetic, is_residual
FROM base;

CREATE OR REFRESH MATERIALIZED VIEW market_share_with_aurora
COMMENT 'Market share per brand and segment including the synthetic Aurora Motors rows'
AS
WITH aurora AS (
  SELECT ref_month, segment, SUM(units) AS aurora_units
  FROM market_brand_monthly WHERE is_synthetic GROUP BY ref_month, segment
),
base AS (
  SELECT b.ref_month, b.segment, b.brand, b.units,
         t.units + COALESCE(a.aurora_units, 0) AS segment_total_units, b.is_synthetic, b.is_residual
  FROM market_brand_monthly b
  JOIN market_segment_totals t ON t.ref_month = b.ref_month AND t.segment = b.segment
  LEFT JOIN aurora a ON a.ref_month = b.ref_month AND a.segment = b.segment
)
SELECT ref_month, segment, brand, units, CAST(segment_total_units AS INT) AS segment_total_units,
       CAST(units AS DOUBLE) / NULLIF(segment_total_units, 0) AS share,
       CASE WHEN is_residual THEN CAST(NULL AS INT)
            ELSE CAST(dense_rank() OVER (PARTITION BY ref_month, segment, is_residual ORDER BY units DESC) AS INT) END AS rank,
       is_synthetic, is_residual
FROM base;
