-- DEV FIXTURE (100% synthetic): minimal stand-in for the synced tables, in an ISOLATED schema.
-- Use for local API tests before the real sync exists:
--   psql ... -v schema=aftersales_lb_dev -f scripts/lakebase/dev_seed.sql
-- and run the app with AFTERSALES_SYNCED_SCHEMA=aftersales_lb_dev AFTERSALES_APP_SCHEMA=aftersales_app_dev.
-- Never run this against the real serving schema (auto_intelligence).
-- Guard: refuse any schema name that does not end in _dev (a typo must never wipe real serving tables).
SELECT (:'schema' LIKE '%\_dev') AS schema_is_dev \gset
\if :schema_is_dev
\else
  \echo 'ERROR: schema name must end in _dev'
  \quit 1
\endif
DROP SCHEMA IF EXISTS :schema CASCADE;
CREATE SCHEMA :schema;
SET search_path = :schema;

CREATE TABLE aftersales_lb_dealers (dealer_id text PRIMARY KEY, dealer_name text, city text, state text, region text, opened_on date, fleet_share double precision);
INSERT INTO aftersales_lb_dealers VALUES
 ('D001','Aurora Motors Campinas','Campinas','SP','Sudeste','2019-03-01',0.5),
 ('D002','Aurora Motors Curitiba','Curitiba','PR','Sul','2019-06-01',0.3),
 ('D003','Aurora Motors Recife','Recife','PE','Nordeste','2020-01-01',0.2);

CREATE TABLE aftersales_lb_parts (part_id text PRIMARY KEY, part_name text, category_id text, category_name text, unit_price_brl double precision, unit_cost_brl double precision, is_critical boolean);
INSERT INTO aftersales_lb_parts VALUES
 ('P001','Pastilha de freio dianteira','brakes','Freios',180,90,true),
 ('P002','Disco de freio dianteiro','brakes','Freios',320,160,true),
 ('P003','Filtro de óleo','filters','Filtros',45,20,false),
 ('P004','Filtro de ar','filters','Filtros',60,28,false);

CREATE TABLE aftersales_lb_model_metrics (model_name text, model_version text PRIMARY KEY, run_id text, cutoff_date date, forecast_date date, holdout_weeks int, n_series int, wape double precision, baseline_wape double precision, bias double precision, baseline_bias double precision, is_champion boolean, logged_at timestamptz);
INSERT INTO aftersales_lb_model_metrics VALUES ('aftersales_demand_forecaster','1','run-dev','2026-08-16','2026-11-16',13,12,0.2,0.3,0.01,0.02,true,now());

CREATE TABLE aftersales_lb_stockout_risk (
  dealer_id text, part_id text, horizon_days int, forecast_date date, stock_units int, on_order_units int, available_units int,
  lead_time_days int, forecast_units double precision, forecast_sigma_units double precision, safety_stock_units double precision,
  days_of_stock double precision, days_to_stockout int, stockout_probability double precision, risk_level text, shortfall_units int,
  lost_sales_brl double precision, action text, recommended_qty int, transfer_from_dealer_id text, transfer_from_excess_units int,
  model_version text, scored_at timestamptz, PRIMARY KEY (dealer_id, part_id, horizon_days));
INSERT INTO aftersales_lb_stockout_risk
SELECT d.dealer_id, p.part_id, h, '2026-11-16', s, 0, s, 7,
       10.0*h/14, 2, 3, s/(10.0/14), NULL, LEAST(1, GREATEST(0, 1 - s/(10.0*h/14))),
       CASE WHEN s < 5*h/14 THEN 'critical' WHEN s < 8*h/14 THEN 'high' WHEN s < 11*h/14 THEN 'medium' ELSE 'low' END,
       GREATEST(0, (10*h/14) - s), GREATEST(0, (10*h/14) - s) * p.unit_price_brl,
       CASE WHEN s >= 11*h/14 THEN 'monitor' WHEN d.dealer_id = 'D001' AND p.part_id = 'P001' THEN 'transfer' ELSE 'reorder' END,
       GREATEST(0, (10*h/14) - s),
       CASE WHEN d.dealer_id = 'D001' AND p.part_id = 'P001' THEN 'D002' END,
       CASE WHEN d.dealer_id = 'D001' AND p.part_id = 'P001' THEN 40 END, '1', now()
FROM aftersales_lb_dealers d CROSS JOIN aftersales_lb_parts p CROSS JOIN (VALUES (14),(28),(56)) hh(h)
CROSS JOIN LATERAL (SELECT (ascii(d.dealer_id) + ascii(right(p.part_id,1)) * 3 + h) % 20 AS s) x;

CREATE TABLE aftersales_lb_forecast_weekly (
  dealer_id text, part_id text, week_start date, is_future boolean, horizon_week int, actual_units double precision, sold_units double precision,
  forecast_units double precision, lower_units double precision, upper_units double precision, baseline_units double precision,
  forecast_date date, model_version text, scored_at timestamptz, PRIMARY KEY (dealer_id, part_id, week_start));
INSERT INTO aftersales_lb_forecast_weekly
SELECT d.dealer_id, p.part_id, w, w >= '2026-11-16', NULL,
       CASE WHEN w < '2026-11-16' THEN 10 + (extract(week from w))::int % 4 END,
       CASE WHEN w < '2026-11-16' THEN 9 + (extract(week from w))::int % 4 END,
       CASE WHEN w >= '2026-08-17' THEN 10.5 END, CASE WHEN w >= '2026-08-17' THEN 7 END, CASE WHEN w >= '2026-08-17' THEN 14 END,
       CASE WHEN w < '2026-11-16' AND w >= '2026-08-17' THEN 11 END, '2026-11-16', '1', now()
FROM aftersales_lb_dealers d CROSS JOIN aftersales_lb_parts p
CROSS JOIN generate_series('2026-05-18'::date, '2027-01-04'::date, interval '7 days') g(w0)
CROSS JOIN LATERAL (SELECT w0::date AS w) x;
