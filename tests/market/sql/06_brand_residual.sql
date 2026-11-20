-- claim: published brands never exceed the segment total and the unpublished tail is 0-3% of it;
--        a month without a brand table is allowed only if listed in market.known_no_brand_table_months
-- returns: offending month x segment rows
WITH b AS (
  SELECT ref_month, segment, sum(units) AS brand_units, count(*) AS n_brands
  FROM __T__market_registrations_brand GROUP BY ref_month, segment
),
no_brand_ok AS (  -- runner fills this from MARKET_KNOWN_NO_BRAND_TABLE_MONTHS
  SELECT to_date(m) AS ref_month FROM (SELECT explode(split('__KNOWN_NO_BRAND__', ',')) AS m) WHERE m <> ''
)
SELECT CAST(t.ref_month AS STRING) AS ref_month, t.segment, t.units AS total_units,
       b.brand_units, b.n_brands, t.brand_table_found,
       round(100 * (t.units - coalesce(b.brand_units, 0)) / t.units, 3) AS residual_pct,
       CASE WHEN t.brand_table_found IS NULL THEN 'null_flag'
            WHEN NOT t.brand_table_found AND t.ref_month NOT IN (SELECT ref_month FROM no_brand_ok) THEN 'no_brand_table_not_allow_listed'
            WHEN NOT t.brand_table_found AND b.brand_units IS NOT NULL THEN 'flag_false_but_brand_rows'
            WHEN t.brand_table_found AND b.brand_units IS NULL THEN 'flag_true_but_no_brand_rows'
            WHEN b.brand_units > t.units THEN 'brands_exceed_total'
            ELSE 'residual_over_3pct' END AS violation
FROM __T__market_segment_totals t LEFT JOIN b USING (ref_month, segment)
WHERE t.brand_table_found IS NULL
   OR (NOT t.brand_table_found AND (t.ref_month NOT IN (SELECT ref_month FROM no_brand_ok) OR b.brand_units IS NOT NULL))
   OR (t.brand_table_found AND (b.brand_units IS NULL OR b.brand_units > t.units
                                OR (t.units - b.brand_units) > 0.03 * t.units))
ORDER BY ref_month, segment
