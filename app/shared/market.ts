/**
 * Contract for the Market screen API (shared by server and client).
 *
 * Endpoints (all GET, JSON, pt-BR formatting is the client's job):
 *   /api/market/summary     latest-month KPIs + data freshness
 *   /api/market/timeseries  monthly series for the selected period
 *   /api/market/brands      brand ranking: latest month and period sum
 *   /api/market/models      top models of the latest month with a model table
 *
 * Data source: gold tables in `${catalog}.${schema}` (see docs/data-model/market.md).
 *
 * Conventions
 * - Months are "YYYY-MM-DD" strings, always the 1st day of the month.
 * - `share` / `*Share` / `changePct` are FRACTIONS (0.034 = 3,4%), never percentages.
 * - Units are integers (vehicles registered). Brand names are as published
 *   (upper case, no accent); the client displays them as received.
 * - Aurora Motors is synthetic: only the `automoveis` segment, from 2019-01.
 *   Where Aurora has no data the Aurora fields are `null` (not 0).
 * - `view=real` never contains Aurora. `view=with_aurora` adds Aurora volume to
 *   the market total and to the share denominator. `realUnits` is identical in
 *   both views, so toggling the view never changes the real market total.
 * - `segment=total` is the sum of `automoveis` and `comerciais_leves`.
 * - Ranks use dense_rank by units (ties share a rank), as in the gold tables, over
 *   non-residual brands; the residual has no rank. Model ranks are row_number by units
 *   (ties broken by brand, model).
 * - `segment=total` derives everything (ranks, shares, Aurora share) from the units
 *   summed across both segments; denominators are always the combined total
 *   (+ Aurora units in view with_aurora).
 * - Validation (HTTP 400, `param` = offending name): values are case-sensitive;
 *   a repeated param (?segment=a&segment=b), an empty value, an unknown value,
 *   a `limit` that is not an integer in range, or a `month` that is not YYYY-MM /
 *   YYYY-MM-01 inside the coverage are all rejected. Unknown extra params are ignored.
 * - Errors: `ApiErrorBody` with HTTP 400 (invalid parameter, pt-BR message), 503
 *   (warehouse unavailable / permission) or 500. Never contains secrets or stacks.
 */

export const MARKET_SEGMENTS = ['automoveis', 'comerciais_leves', 'total'] as const;
export const MARKET_PERIODS = ['12m', '24m', '60m', 'all'] as const;
export const MARKET_VIEWS = ['real', 'with_aurora'] as const;

export type MarketSegment = (typeof MARKET_SEGMENTS)[number];
/** Window ending at the latest available month: last 12/24/60 months, or the whole history (2003-01..). */
export type MarketPeriod = (typeof MARKET_PERIODS)[number];
export type MarketView = (typeof MARKET_VIEWS)[number];

export const MARKET_DEFAULTS = {
  segment: 'total',
  period: '24m',
  view: 'with_aurora',
} as const satisfies { segment: MarketSegment; period: MarketPeriod; view: MarketView };

/** Query string accepted by every endpoint. Omitted params use MARKET_DEFAULTS; unknown values give 400. */
export interface MarketQuery {
  segment?: MarketSegment;
  period?: MarketPeriod;
  view?: MarketView;
  /**
   * Reference month "YYYY-MM" (or "YYYY-MM-01"); summary, brands and models only.
   * Default = latest month. Outside the coverage => 400. For brands, the `period`
   * window ends at this month. /timeseries ignores it (window ends at the latest month).
   */
  month?: string;
}

/** Extra query param for /brands and /models: max rows (brands: 1..25, default 10; models: 1..50, default 10). */
export interface MarketLimitQuery extends MarketQuery {
  limit?: number;
}

/** Echo of the parameters the server actually applied (after defaults). */
export interface MarketAppliedQuery {
  segment: MarketSegment;
  period: MarketPeriod;
  view: MarketView;
  /** Reference month actually used (the default, latest month, when not given). "YYYY-MM-01". */
  month: string;
}

export interface MarketMeta {
  query: MarketAppliedQuery;
  /** ISO timestamp when the oldest underlying query result was loaded from the warehouse (older than now when `cached`). */
  generatedAt: string;
  /** True when served from the server's in-memory cache. */
  cached: boolean;
}

// ---------- GET /api/market/summary ----------

export interface MarketSummaryResponse {
  meta: MarketMeta;
  /** Reference month of every KPI (query.month, default the latest month with data). */
  month: string;
  /** Same month one year earlier (YoY base). */
  previousYearMonth: string;
  /** Data freshness: first and last month loaded, and number of months. */
  coverage: { firstMonth: string; lastMonth: string; monthsCount: number };
  market: {
    /** Published real total for the segment (no Aurora). Same in both views. */
    realUnits: number;
    /** Aurora units in the month; null when Aurora does not apply (segment comerciais_leves, view real). */
    auroraUnits: number | null;
    /** Market total of the selected view: realUnits (real) or realUnits + auroraUnits (with_aurora). */
    totalUnits: number;
    /** Same measure one year earlier; null when the year-earlier month has no data. */
    previousYearUnits: number | null;
    /**
     * (totalUnits / previousYearUnits) - 1, fraction; null when previousYearUnits is null or 0.
     * Same basis as totalUnits: view real = real vs real; with_aurora = (real + Aurora) vs (real + Aurora).
     * The client label must say which basis is shown.
     */
    yoyPct: number | null;
  };
  /** null when Aurora does not apply to the selection (view=real or segment=comerciais_leves). */
  aurora: {
    units: number;
    /** Aurora units / totalUnits of the selected view (fraction). */
    share: number;
    /** Dense rank among non-residual brands in the with_aurora view; null if not ranked. */
    rank: number | null;
    /** Number of ranked brands that month (rank denominator, residual excluded). */
    rankedBrands: number;
    /** Share one year earlier; null when Aurora did not exist then. */
    previousYearShare: number | null;
    /** Percentage-point change in share vs a year earlier, as a fraction (0.004 = +0,4 p.p.); null when unknown. */
    shareChangePp: number | null;
  } | null;
}

// ---------- GET /api/market/timeseries ----------

export interface MarketTimeseriesPoint {
  month: string;
  /** Published real total (no Aurora). */
  realUnits: number;
  /** Aurora units; null when Aurora does not apply (before 2019-01, comerciais_leves, view real). */
  auroraUnits: number | null;
  /** realUnits (view real) or realUnits + auroraUnits (with_aurora). */
  totalUnits: number;
  /** auroraUnits / totalUnits (fraction); null when auroraUnits is null. */
  auroraShare: number | null;
}

export interface MarketTimeseriesResponse {
  meta: MarketMeta;
  /** Inclusive window actually returned (months, ascending, no gaps). */
  from: string;
  to: string;
  points: MarketTimeseriesPoint[];
}

// ---------- GET /api/market/brands ----------

export interface MarketBrandRow {
  /** 1-based rank among non-residual brands for this list; null on the residual row. */
  rank: number | null;
  /** Brand name as published; the residual row is "OUTRAS (NAO PUBLICADAS)". */
  brand: string;
  /** Display label: same as `brand`, except the residual is "Outras (não publicadas)" and Aurora "Aurora Motors". */
  label: string;
  units: number;
  /** units / list totalUnits (fraction). */
  share: number;
  isAurora: boolean;
  /** Residual row: market not published in the top-N ranking. Always last in the list, rank null. */
  isResidual: boolean;
}

export interface MarketBrandList {
  /** Inclusive month range covered (from === to for the latest-month list). */
  from: string;
  to: string;
  /** Total units of the scope = sum of all rows incl. residual (and Aurora in with_aurora). */
  totalUnits: number;
  /** Top `limit` brands by units, then the residual row (always present when residual units > 0). */
  rows: MarketBrandRow[];
  /**
   * Units of the non-residual brands cut off by `limit`; 0 when nothing was cut.
   * Invariants: sum(rows.units) + othersUnits === totalUnits and
   * sum(rows.share) + othersUnits / totalUnits === 1.
   */
  othersUnits: number;
}

export interface MarketBrandsResponse {
  meta: MarketMeta;
  /** Ranking of the reference month. In 2004-01-like preview months the list holds only the residual (100%). */
  latestMonth: MarketBrandList;
  /**
   * Sum over the selected period. Brands outside the published top-N in some months are partly in the
   * residual, so period ranks are indicative (the residual absorbs the remainder; totals stay exact).
   */
  period: MarketBrandList;
}

// ---------- GET /api/market/models ----------

export interface MarketModelRow {
  /** 1-based row_number by units (ties by brand, model); segment=total merges both segments. */
  rank: number;
  brand: string;
  model: string;
  units: number;
  /** units / totalUnits (fraction): combined total of the selection for `month` (+ Aurora in with_aurora). */
  share: number;
  isAurora: boolean;
}

export interface MarketModelsResponse {
  meta: MarketMeta;
  /** Month shown. Equals the requested month unless it has no model table (then the closest earlier one that has). */
  month: string;
  /** The month requested (query.month, default latest), for the "data refers to <month>" notice when `month` differs. */
  latestMonth: string;
  /** False => `rows` is empty (no model table for any month of the selection). */
  available: boolean;
  /**
   * Models are the published top 50 only, so rows sum to less than the total (no residual for models).
   * `coveredUnits` = sum of ALL published models (before `limit`); `totalUnits` = scope total.
   */
  coveredUnits: number;
  totalUnits: number;
  rows: MarketModelRow[];
}

// ---------- errors ----------

export type ApiErrorCode = 'invalid_parameter' | 'warehouse_unavailable' | 'internal_error';

export interface ApiErrorBody {
  error: {
    code: ApiErrorCode;
    /** Short, sanitized pt-BR message (400) or generic English text (5xx). Safe to display. */
    message: string;
    /** Name of the offending query param for invalid_parameter. */
    param?: string;
  };
}
