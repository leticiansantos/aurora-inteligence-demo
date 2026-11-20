-- claim: every month from 2003-01 to the latest parsed month has published totals (only market.known_missing_months may be absent)
-- returns: one row per expected month absent from market_segment_totals and not in the allow-list
WITH bounds AS (SELECT max(ref_month) AS last_month FROM __T__market_segment_totals),
expected AS (
  SELECT explode(sequence(DATE'2003-01-01', last_month, INTERVAL 1 MONTH)) AS ref_month FROM bounds
),
allowed_gaps AS (  -- runner fills this from MARKET_KNOWN_MISSING_MONTHS (mirror of market.known_missing_months)
  SELECT to_date(m) AS ref_month FROM (SELECT explode(split('__KNOWN_MISSING__', ',')) AS m) WHERE m <> ''
)
SELECT CAST(e.ref_month AS STRING) AS ref_month, 'month_absent' AS violation
FROM expected e
LEFT ANTI JOIN __T__market_segment_totals t ON t.ref_month = e.ref_month
WHERE e.ref_month NOT IN (SELECT ref_month FROM allowed_gaps)
UNION ALL
SELECT CAST(ref_month AS STRING), 'allow_listed_month_present'
FROM allowed_gaps WHERE ref_month IN (SELECT ref_month FROM __T__market_segment_totals)
ORDER BY 1
