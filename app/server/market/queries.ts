/**
 * Parameterized SQL for the Market screen. Values are always bound parameters;
 * only the catalog/schema identifiers are interpolated, and they are validated
 * upstream (plain Unity Catalog identifiers, see server.ts).
 *
 * Segment filter: `:segment = 'total'` matches both segments.
 */
export interface MarketTables {
  totals: string;
  brandMonthly: string;
  modelMonthly: string;
}

export function marketTables(catalog: string, schema: string): MarketTables {
  const base = `\`${catalog}\`.\`${schema}\``;
  return {
    totals: `${base}.market_segment_totals`,
    brandMonthly: `${base}.market_brand_monthly`,
    modelMonthly: `${base}.market_model_monthly`,
  };
}

const SEGMENT = `(:segment = 'total' OR segment = :segment)`;

export function coverageSql(t: MarketTables): string {
  return `SELECT CAST(min(ref_month) AS STRING) AS first_month,
       CAST(max(ref_month) AS STRING) AS last_month,
       count(DISTINCT ref_month) AS months_count
FROM ${t.totals}`;
}

/** Real published total and Aurora units per month, inclusive window [:from_month, :to_month]. */
export function seriesSql(t: MarketTables): string {
  return `WITH real_totals AS (
  SELECT ref_month, sum(units) AS real_units
  FROM ${t.totals}
  WHERE ${SEGMENT} AND ref_month BETWEEN :from_month AND :to_month
  GROUP BY ref_month
), aurora AS (
  SELECT ref_month, sum(units) AS aurora_units
  FROM ${t.brandMonthly}
  WHERE is_synthetic AND ${SEGMENT} AND ref_month BETWEEN :from_month AND :to_month
  GROUP BY ref_month
)
SELECT CAST(r.ref_month AS STRING) AS month, r.real_units, a.aurora_units
FROM real_totals r LEFT JOIN aurora a ON a.ref_month = r.ref_month
ORDER BY r.ref_month`;
}

/** Units per brand (real, residual, Aurora) summed over [:from_month, :to_month]. */
export function brandsSql(t: MarketTables): string {
  return `SELECT brand, is_synthetic, is_residual, sum(units) AS units
FROM ${t.brandMonthly}
WHERE ${SEGMENT} AND ref_month BETWEEN :from_month AND :to_month
GROUP BY brand, is_synthetic, is_residual`;
}

/** Models of the latest month <= :month that has a model table for the selection. */
export function modelsSql(t: MarketTables): string {
  return `WITH latest AS (
  SELECT max(ref_month) AS ref_month
  FROM ${t.modelMonthly}
  WHERE ${SEGMENT} AND ref_month <= :month
)
SELECT CAST(m.ref_month AS STRING) AS month, m.brand, m.model, m.is_synthetic, sum(m.units) AS units
FROM ${t.modelMonthly} m JOIN latest l ON m.ref_month = l.ref_month
WHERE (:segment = 'total' OR m.segment = :segment)
GROUP BY m.ref_month, m.brand, m.model, m.is_synthetic`;
}
