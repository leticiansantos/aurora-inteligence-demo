-- claim: synthetic rows are only Aurora Motors (IPE/JATOBA/AROEIRA), automoveis, months with totals from 2019-01,
--        flagged is_synthetic, and monthly volume = round(share x total / (1 - share)) within rounding
-- returns: offending synthetic rows
WITH m AS (
  SELECT s.ref_month, sum(s.units) AS u, min(s.target_share) AS share_min, max(s.target_share) AS share_max, max(t.units) AS total
  FROM __T__market_synthetic_registrations s
  JOIN __T__market_segment_totals t ON t.ref_month = s.ref_month AND t.segment = 'automoveis'
  GROUP BY s.ref_month
)
SELECT 'rule_violation' AS violation, CAST(ref_month AS STRING) AS ref_month, segment, brand, model, units
FROM __T__market_synthetic_registrations
WHERE NOT coalesce(is_synthetic, false) OR brand <> 'AURORA MOTORS' OR segment <> 'automoveis'
   OR ref_month < DATE'2019-01-01' OR units IS NULL OR units < 0
   OR model NOT IN ('IPE', 'JATOBA', 'AROEIRA') OR target_share IS NULL OR seed IS NULL
UNION ALL
SELECT 'duplicate_key', CAST(ref_month AS STRING), segment, brand, model, count(*)
FROM __T__market_synthetic_registrations GROUP BY ref_month, segment, brand, model HAVING count(*) > 1
UNION ALL
SELECT 'no_synthetic_after_launch', CAST(t.ref_month AS STRING), 'automoveis', 'AURORA MOTORS', '-', 0
FROM __T__market_segment_totals t
LEFT ANTI JOIN __T__market_synthetic_registrations s ON s.ref_month = t.ref_month
WHERE t.segment = 'automoveis' AND t.ref_month >= DATE'2019-01-01'
UNION ALL
SELECT 'synthetic_month_without_totals', CAST(s.ref_month AS STRING), s.segment, s.brand, s.model, s.units
FROM __T__market_synthetic_registrations s
LEFT ANTI JOIN __T__market_segment_totals t ON t.ref_month = s.ref_month AND t.segment = 'automoveis'
UNION ALL
SELECT 'volume_ne_share_formula', CAST(ref_month AS STRING), 'automoveis', 'AURORA MOTORS',
       CAST(round(share_max * total / (1 - share_max)) AS STRING), u
FROM m
WHERE share_min <> share_max OR abs(u - share_max * total / (1 - share_max)) > 3
