CREATE OR REFRESH MATERIALIZED VIEW market_model_monthly
COMMENT 'Monthly units per model and segment: real top 50 plus synthetic Aurora models'
AS
SELECT ref_month, segment, brand, model, CAST(units AS INT) AS units, rank, false AS is_synthetic
FROM market_registrations_model
UNION ALL
SELECT ref_month, segment, brand, model, CAST(units AS INT) AS units, CAST(NULL AS INT) AS rank, true AS is_synthetic
FROM market_synthetic_registrations;
