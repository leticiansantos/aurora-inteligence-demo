-- claim: market_registrations_brand is real-only, unique on (ref_month, segment, brand), no nulls, units >= 0,
--        published rank >= 1, only months with totals
-- returns: offending rows
SELECT 'duplicate_key' AS violation, CAST(ref_month AS STRING) AS ref_month, segment, brand, count(*) AS n
FROM __T__market_registrations_brand GROUP BY ref_month, segment, brand HAVING count(*) > 1
UNION ALL
SELECT 'null_or_negative', CAST(ref_month AS STRING), segment, brand, units
FROM __T__market_registrations_brand
WHERE ref_month IS NULL OR segment IS NULL OR brand IS NULL OR trim(brand) = '' OR units IS NULL OR units < 0
   OR rank IS NULL OR rank < 1
UNION ALL
SELECT 'synthetic_in_real', CAST(ref_month AS STRING), segment, brand, units
FROM __T__market_registrations_brand WHERE upper(brand) LIKE '%AURORA%' OR brand = 'OUTRAS (NAO PUBLICADAS)'
UNION ALL
SELECT 'unknown_segment', CAST(ref_month AS STRING), segment, brand, units
FROM __T__market_registrations_brand WHERE segment NOT IN ('automoveis', 'comerciais_leves')
UNION ALL
SELECT 'month_without_totals', CAST(b.ref_month AS STRING), b.segment, b.brand, b.units
FROM __T__market_registrations_brand b LEFT ANTI JOIN __T__market_segment_totals t USING (ref_month, segment)
UNION ALL
SELECT 'rank_order_or_start', CAST(a.ref_month AS STRING), a.segment, a.brand, a.rank
FROM __T__market_registrations_brand a JOIN __T__market_registrations_brand b ON a.ref_month = b.ref_month AND a.segment = b.segment
WHERE a.units > b.units AND a.rank > b.rank  -- ties allowed; higher units never ranked below
UNION ALL
SELECT 'no_rank_1', CAST(ref_month AS STRING), segment, '-', min(rank)
FROM __T__market_registrations_brand GROUP BY ref_month, segment HAVING min(rank) <> 1
