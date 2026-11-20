-- claim: real gold brand rows (incl. one residual) sum exactly to the published total; residual and Aurora rows
--        have rank NULL; Aurora rows equal the synthetic silver; unique on (ref_month, segment, brand)
-- returns: offending month x segment or rows
WITH g AS (
  SELECT ref_month, segment, sum(units) AS gold_units
  FROM __T__market_brand_monthly WHERE NOT is_synthetic GROUP BY ref_month, segment
), ga AS (
  SELECT ref_month, segment, sum(units) AS u FROM __T__market_brand_monthly WHERE is_synthetic GROUP BY ref_month, segment
), sa AS (
  SELECT ref_month, segment, sum(units) AS u FROM __T__market_synthetic_registrations GROUP BY ref_month, segment
)
SELECT 'real_gold_ne_total' AS violation, CAST(coalesce(t.ref_month, g.ref_month) AS STRING) AS ref_month,
       coalesce(t.segment, g.segment) AS segment, t.units AS expected, g.gold_units AS actual
FROM __T__market_segment_totals t FULL OUTER JOIN g ON g.ref_month = t.ref_month AND g.segment = t.segment
WHERE g.gold_units IS NULL OR t.units IS NULL OR g.gold_units <> t.units
UNION ALL
SELECT 'bad_residual_row', CAST(ref_month AS STRING), segment, 0, units
FROM __T__market_brand_monthly
WHERE is_residual AND (is_synthetic OR units < 0 OR rank IS NOT NULL OR brand <> 'OUTRAS (NAO PUBLICADAS)')
UNION ALL
SELECT 'bad_flags_or_rank', CAST(ref_month AS STRING), segment, 0, units
FROM __T__market_brand_monthly
WHERE is_synthetic IS NULL OR is_residual IS NULL
   OR (is_synthetic AND (brand <> 'AURORA MOTORS' OR rank IS NOT NULL))
   OR (NOT is_synthetic AND NOT is_residual AND (rank IS NULL OR upper(brand) LIKE '%AURORA%'))
UNION ALL
SELECT 'residual_count_ne_1', CAST(ref_month AS STRING), segment, 1, count_if(is_residual)
FROM __T__market_brand_monthly WHERE NOT is_synthetic
GROUP BY ref_month, segment HAVING count_if(is_residual) <> 1
UNION ALL
SELECT 'aurora_gold_ne_silver', CAST(coalesce(ga.ref_month, sa.ref_month) AS STRING), coalesce(ga.segment, sa.segment), sa.u, ga.u
FROM ga FULL OUTER JOIN sa ON sa.ref_month = ga.ref_month AND sa.segment = ga.segment
WHERE ga.u IS NULL OR sa.u IS NULL OR ga.u <> sa.u
UNION ALL
SELECT 'duplicate_key', CAST(ref_month AS STRING), segment, 1, count(*)
FROM __T__market_brand_monthly GROUP BY ref_month, segment, brand HAVING count(*) > 1
