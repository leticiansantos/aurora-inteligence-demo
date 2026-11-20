-- Oracle for GET /api/market/summary at :month (KPIs), independent of the share_* gold tables.
-- Params: :month DATE, :segment STRING (automoveis|comerciais_leves|total), :view STRING (real|with_aurora)
WITH real AS (
  SELECT ref_month, sum(units) AS real_units
  FROM classic_stable.auto_intelligence.market_segment_totals
  WHERE ref_month IN (:month, add_months(:month, -12))
    AND (:segment = 'total' OR segment = :segment)
  GROUP BY ref_month
), aur AS (
  SELECT ref_month, sum(units) AS aurora_units
  FROM classic_stable.auto_intelligence.market_brand_monthly
  WHERE is_synthetic AND :view = 'with_aurora'
    AND ref_month IN (:month, add_months(:month, -12))
    AND (:segment = 'total' OR segment = :segment)
  GROUP BY ref_month
), m AS (
  SELECT r.ref_month, r.real_units, a.aurora_units, r.real_units + coalesce(a.aurora_units, 0) AS total_units
  FROM real r LEFT JOIN aur a USING (ref_month)
), ranked AS (
  SELECT brand, is_synthetic,
         dense_rank() OVER (ORDER BY sum(units) DESC) AS rnk
  FROM classic_stable.auto_intelligence.market_brand_monthly
  WHERE ref_month = :month AND NOT is_residual
    AND (:segment = 'total' OR segment = :segment)
    AND (:view = 'with_aurora' OR NOT is_synthetic)
  GROUP BY brand, is_synthetic
)
SELECT cur.ref_month                                             AS month,
       cur.real_units                                            AS real_units,
       cur.aurora_units                                          AS aurora_units,
       cur.total_units                                           AS total_units,
       prev.total_units                                          AS previous_year_units,
       cur.total_units / prev.total_units - 1                    AS yoy_pct,
       cur.aurora_units / cur.total_units                        AS aurora_share,
       prev.aurora_units / prev.total_units                      AS aurora_previous_year_share,
       cur.aurora_units / cur.total_units
         - prev.aurora_units / prev.total_units                  AS aurora_share_change_pp,
       (SELECT max(rnk) FILTER (WHERE is_synthetic) FROM ranked) AS aurora_rank,
       (SELECT count(*) FROM ranked)                             AS ranked_brands
FROM m cur LEFT JOIN m prev ON prev.ref_month = add_months(cur.ref_month, -12)
WHERE cur.ref_month = :month
