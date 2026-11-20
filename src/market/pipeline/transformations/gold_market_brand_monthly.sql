-- Residual per month and segment: published total minus the published brand rows (ADR D3).
CREATE OR REFRESH MATERIALIZED VIEW market_brand_residual (
  CONSTRAINT listed_not_above_total EXPECT (raw_residual >= 0),
  CONSTRAINT residual_in_range EXPECT (
    residual_units <= 0.03 * total_units
    OR array_contains(split('${market.known_no_brand_table_months}', ','), date_format(ref_month, 'yyyy-MM'))
  )
)
AS SELECT
  t.ref_month,
  t.segment,
  t.units AS total_units,
  t.units - COALESCE(SUM(b.units), 0) AS raw_residual,
  GREATEST(t.units - COALESCE(SUM(b.units), 0), 0) AS residual_units
FROM market_segment_totals t
LEFT JOIN market_registrations_brand b ON b.ref_month = t.ref_month AND b.segment = t.segment
GROUP BY t.ref_month, t.segment, t.units;

-- Real brands + residual + synthetic (Aurora) rows. Sums exactly to the published total when real only.
CREATE OR REFRESH MATERIALIZED VIEW market_brand_monthly
COMMENT 'Monthly units per brand and segment: real top brands, residual row and synthetic Aurora rows'
AS
SELECT ref_month, segment, brand, CAST(units AS INT) AS units, rank,
       false AS is_synthetic, false AS is_residual
FROM market_registrations_brand
UNION ALL
SELECT ref_month, segment, 'OUTRAS (NAO PUBLICADAS)' AS brand, CAST(residual_units AS INT) AS units,
       CAST(NULL AS INT) AS rank, false AS is_synthetic, true AS is_residual
FROM market_brand_residual
UNION ALL
SELECT ref_month, segment, brand, CAST(SUM(units) AS INT) AS units, CAST(NULL AS INT) AS rank,
       true AS is_synthetic, false AS is_residual
FROM market_synthetic_registrations
GROUP BY ref_month, segment, brand;
