-- Fleet integration with Tela 1: registrations x fleet_share, cumulative, no scrappage (data model §4 fleet_monthly)
WITH src_all AS (SELECT ref_month, model, sum(units) units FROM __T__market_synthetic_registrations GROUP BY ALL),
f AS (SELECT * FROM __T__aftersales_fleet_monthly),
exp AS (SELECT s.ref_month, d.dealer_id, s.model, s.units * d.fleet_share AS reg,
               sum(s.units * d.fleet_share) OVER (PARTITION BY d.dealer_id, s.model ORDER BY s.ref_month) AS cum
        FROM src_all s CROSS JOIN __T__aftersales_dealers d)
SELECT 'fleet: per-model total == source registrations' AS check,
       max(abs(fl - su)) < 1e-6 AS ok, to_json(collect_list(struct(model, fl, su))) AS detail
FROM (SELECT s.model, f2.fl, s.su FROM (SELECT model, sum(units) su FROM src_all GROUP BY model) s
      FULL OUTER JOIN (SELECT model, sum(registrations_units) fl FROM f GROUP BY model) f2 ON f2.model = s.model)
UNION ALL SELECT 'fleet: grand total == 380258 (sum of source)', abs(sum(registrations_units) - (SELECT sum(units) FROM src_all)) < 1e-6, cast(sum(registrations_units) AS STRING) FROM f
UNION ALL SELECT 'fleet: row-level == units x fleet_share and cumulative active fleet', count_if(e.ref_month IS NULL OR f.ref_month IS NULL OR abs(e.reg - f.registrations_units) > 1e-6 OR abs(e.cum - f.active_fleet_units) > 1e-6) = 0,
       concat('mismatch=', count_if(e.ref_month IS NULL OR f.ref_month IS NULL OR abs(e.reg - f.registrations_units) > 1e-6 OR abs(e.cum - f.active_fleet_units) > 1e-6), ' rows=', count(*))
FROM exp e FULL OUTER JOIN f ON e.ref_month = f.ref_month AND e.dealer_id = f.dealer_id AND e.model = f.model
UNION ALL SELECT 'fleet: range 2019-01..2026-09', min(ref_month) = DATE'2019-01-01' AND max(ref_month) = DATE'2026-09-01', concat(min(ref_month), '..', max(ref_month)) FROM f
