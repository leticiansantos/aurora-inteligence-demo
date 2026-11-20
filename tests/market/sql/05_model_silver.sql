-- claim: market_registrations_model is real-only, unique on (ref_month, segment, brand, model), ranked, no nulls,
--        never sums above the published total
-- returns: offending rows (unmatched brands and models starting with the brand are reported in quality.txt:
--          the PDF itself prints e.g. 'MPLM/MPLM/JAVALI', so a brand prefix in the model is not a defect)
SELECT 'duplicate_key' AS violation, CAST(ref_month AS STRING) AS ref_month, segment, brand, model, count(*) AS n
FROM __T__market_registrations_model GROUP BY ref_month, segment, brand, model HAVING count(*) > 1
UNION ALL
SELECT 'null_or_negative', CAST(ref_month AS STRING), segment, brand, model, units
FROM __T__market_registrations_model
WHERE ref_month IS NULL OR segment IS NULL OR brand IS NULL OR model IS NULL OR trim(model) = ''
   OR units IS NULL OR units < 0 OR rank IS NULL OR rank < 1 OR brand_matched IS NULL
UNION ALL
SELECT 'synthetic_in_real', CAST(ref_month AS STRING), segment, brand, model, units
FROM __T__market_registrations_model WHERE upper(brand) LIKE '%AURORA%'
UNION ALL
SELECT 'top_n_exceeds_total', CAST(m.ref_month AS STRING), m.segment, 'sum(models)', CAST(sum(m.units) AS STRING), max(t.units)
FROM __T__market_registrations_model m
JOIN __T__market_segment_totals t USING (ref_month, segment)
GROUP BY m.ref_month, m.segment HAVING sum(m.units) > max(t.units)
