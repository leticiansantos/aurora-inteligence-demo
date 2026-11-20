/**
 * Contract for the Aftersales ("Pós-venda") screen API (shared by server and client).
 * DRAFT v1: shapes are settled; the field set may only grow (additive) without notice,
 * any breaking change is negotiated with the frontend first.
 *
 * Endpoints (JSON, pt-BR formatting is the client's job):
 *   GET  /api/aftersales/filters         allowed filter values (dealers, categories, horizons) + freshness
 *   GET  /api/aftersales/summary         KPIs for the selected filters
 *   GET  /api/aftersales/forecast        forecast x actual series (weekly)
 *   GET  /api/aftersales/risk            stockout-risk ranking with recommended action
 *   POST /api/aftersales/requests        create a replenishment / transfer request (writes to Lakebase)
 *   GET  /api/aftersales/requests        list requests (newest first), optional status filter
 *   GET  /api/aftersales/requests/:id    one request (status polling)
 *
 * Data sources: forecast / risk / stock / KPIs are read from Lakebase synced tables
 * (copies of the gold tables in `${catalog}.${schema}`, see docs/data-model/aftersales.md);
 * requests live in the Lakebase OLTP table `aftersales_replenishment_requests`.
 * All data is 100% synthetic.
 *
 * Conventions
 * - Dates are "YYYY-MM-DD" strings; weeks are identified by their Monday.
 * - Money is BRL as a plain number (reais, not cents); quantities are integers (units of the part).
 * - `fillRate` is a FRACTION (0.93 = 93%), never a percentage.
 * - Filters: omitted or "all" = no filter. Values are case-sensitive and validated against
 *   /filters; a repeated param, empty value or unknown value => HTTP 400 with `param`.
 * - Consistency rules (tested by QA):
 *   partsAtRisk.value = riskDistribution.critical + riskDistribution.high;
 *   sum(riskDistribution) = /risk `total` with minLevel=low (same filters);
 *   lostSalesAvoidedBrl.value = sum of /risk `lostSalesBrl` over rows with action != "monitor"
 *   (decided: the recommended action is assumed to cover the whole gap; lostSalesBrl = lost_units x
 *   unit price, i.e. revenue, as in docs/data-model/aftersales.md);
 *   daysOfStock.value = sum(stockUnits) / (sum(forecastUnits) / horizon) over the selection
 *   (demand-weighted; null when the selection has no forecast demand);
 *   `previous` is null (never 0) when no older forecast snapshot exists;
 *   /forecast `series` ignores `horizon`: it always spans the 26 history weeks plus 8 future weeks
 *   (aftersales_forecast_weekly); forecast/interval are filled for the 13-week holdout and the future weeks.
 * - Request rules (POST /requests, validated server-side, 400 + `param` unless noted):
 *   body must be JSON (Content-Type application/json, max 16 KB; otherwise 400 param "body");
 *   unknown fields => 400 param=<field>; `quantity` must be a JSON integer 1..100000 (strings,
 *   decimals, null, 0, negatives => 400 param "quantity"); `dealerId` / `partId` must exist, and the
 *   dealer x part must exist in the risk table (else 400); `note` is trimmed, blank => stored as null, >500 chars or
 *   control characters (incl. NUL) => 400 param "note"; emoji allowed.
 *   type=transfer requires `fromDealerId` (known dealer, != dealerId) and quantity <= the donor's
 *   on-hand units (stock_units of the donor's risk row, same horizon); transfer is allowed even when /risk recommends
 *   reorder (and vice versa). type=reorder with `fromDealerId` => 400 param "fromDealerId".
 *   Duplicate rule: at most ONE active (open | approved | in_transit) request per dealer x part x type, enforced by a partial unique
 *   index in Postgres; a violation (23505) maps to 409 duplicate_request (race-safe).
 *   GET /requests/:id with a non-UUID id => 400 param "id"; unknown UUID => 404.
 * - `openRequest` in /risk = the most recent request for that dealer x part whose status is
 *   open | approved | in_transit (cancelled / fulfilled requests are ignored); null when none is active.
 * - Errors: `ApiErrorBody` (same shape as the market API) with HTTP 400 (invalid parameter,
 *   pt-BR message), 404 (request not found), 409 (duplicate open request),
 *   503 (warehouse / Lakebase unavailable) or 500. Never contains secrets or stacks.
 */

export const AFTERSALES_HORIZONS = [14, 28, 56] as const;
/** Forecast horizon in days, counted from the forecast date. */
export type AftersalesHorizon = (typeof AFTERSALES_HORIZONS)[number];
export const AFTERSALES_DEFAULT_HORIZON: AftersalesHorizon = 28;

export const AFTERSALES_ACTIONS = ['reorder', 'transfer', 'monitor'] as const;
/**
 * reorder  = buy from the central warehouse / supplier (lead time applies);
 * transfer = move stock from another dealer with surplus (see `transferFrom`);
 * monitor  = risk is low, no action recommended.
 */
export type AftersalesAction = (typeof AFTERSALES_ACTIONS)[number];

export const AFTERSALES_RISK_LEVELS = ['critical', 'high', 'medium', 'low'] as const;
export type AftersalesRiskLevel = (typeof AFTERSALES_RISK_LEVELS)[number];

export const AFTERSALES_REQUEST_TYPES = ['reorder', 'transfer'] as const;
export type AftersalesRequestType = (typeof AFTERSALES_REQUEST_TYPES)[number];

/** Request lifecycle. The app creates `open`; advancing it is out of scope for the demo UI. */
export const AFTERSALES_REQUEST_STATUSES = ['open', 'approved', 'in_transit', 'fulfilled', 'cancelled'] as const;
export type AftersalesRequestStatus = (typeof AFTERSALES_REQUEST_STATUSES)[number];

/** Query string shared by /summary, /forecast and /risk. */
export interface AftersalesQuery {
  /** Dealer id from /filters (e.g. "D001"). Default: all dealers. */
  dealer?: string;
  /** Part category id from /filters (e.g. "brakes"). Default: all categories. */
  category?: string;
  /** Default AFTERSALES_DEFAULT_HORIZON. */
  horizon?: AftersalesHorizon;
}

/** /forecast only: restrict the series to one part (drill-down from a ranking row). */
export interface AftersalesForecastQuery extends AftersalesQuery {
  partId?: string;
}

/** /risk only. */
export interface AftersalesRiskQuery extends AftersalesQuery {
  /** Minimum level to include (default "low" = everything). */
  minLevel?: AftersalesRiskLevel;
  /** Max rows, integer 1..200, default 50. */
  limit?: number;
}

/** Echo of the parameters actually applied (after defaults). null = no filter. */
export interface AftersalesAppliedQuery {
  dealer: string | null;
  category: string | null;
  horizon: AftersalesHorizon;
}

export interface AftersalesMeta {
  query: AftersalesAppliedQuery;
  /** Date the forecast was produced for (first forecast day). "YYYY-MM-DD". */
  forecastDate: string;
  /** Last day with actual sales/stock data. "YYYY-MM-DD". */
  dataThrough: string;
  /** Forecast model identification, e.g. "aftersales_forecast@champion v3". */
  modelVersion: string;
  /** ISO timestamp of the last Lakebase sync of the served tables. */
  syncedAt: string | null;
  /** The data is synthetic (the client shows the badge). */
  synthetic: true;
}

// ---------------------------------------------------------------- /filters

export interface AftersalesDealerOption {
  id: string;
  name: string;
  city: string;
  state: string;
}
export interface AftersalesCategoryOption {
  id: string;
  /** pt-BR display name, e.g. "Freios". */
  name: string;
}
export interface AftersalesFiltersResponse {
  dealers: AftersalesDealerOption[];
  categories: AftersalesCategoryOption[];
  horizons: readonly AftersalesHorizon[];
  defaultHorizon: AftersalesHorizon;
  meta: Omit<AftersalesMeta, 'query'>;
}

// ---------------------------------------------------------------- /summary

export interface AftersalesKpi {
  /** null when the denominator is 0 (no demand in the selection): show "-", not 0. */
  value: number | null;
  /** Same KPI over the previous comparable window; null when unavailable. */
  previous: number | null;
}
export interface AftersalesSummaryResponse {
  meta: AftersalesMeta;
  kpis: {
    /** Dealer x part pairs with risk level critical or high within the horizon. */
    partsAtRisk: AftersalesKpi;
    /** BRL (revenue: units x price) of lost sales avoided if the recommended actions are executed. */
    lostSalesAvoidedBrl: AftersalesKpi;
    /** sum(sold) / sum(demand) over the last 4 history weeks of the selection (fraction). */
    fillRate: AftersalesKpi;
    /** Stock on hand / forecast daily demand, in days (demand-weighted over the selection). */
    daysOfStock: AftersalesKpi;
  };
  /** Count of dealer x part pairs per risk level (selection total = sum). */
  riskDistribution: Record<AftersalesRiskLevel, number>;
}

// ---------------------------------------------------------------- /forecast

export interface AftersalesForecastPoint {
  /** Monday of the week. */
  weekStart: string;
  /** Units sold; null for future weeks. */
  actualUnits: number | null;
  /** Forecast units; null for weeks before the backtest window. */
  forecastUnits: number | null;
  /** 80% prediction interval; null when no forecast. */
  lowerUnits: number | null;
  upperUnits: number | null;
  /** True when weekStart >= forecastDate (the point is a future forecast). */
  isFuture: boolean;
}
export interface AftersalesForecastResponse {
  meta: AftersalesMeta;
  /** x-axis = week (Monday), y-axis = units summed over the selection. */
  series: AftersalesForecastPoint[];
  /** Backtest quality over the holdout window (same selection). */
  accuracy: {
    /** Weighted absolute percentage error of the model (fraction). */
    wape: number;
    /** Same metric for the seasonal-naive baseline (fraction). */
    baselineWape: number;
  } | null;
}

// ---------------------------------------------------------------- /risk

export interface AftersalesRiskRow {
  /** Stable key "<dealerId>:<partId>". */
  key: string;
  dealerId: string;
  dealerName: string;
  partId: string;
  partName: string;
  categoryId: string;
  categoryName: string;
  /** On-hand units. */
  stockUnits: number;
  /** Units on order (already requested from the supplier). */
  onOrderUnits: number;
  /** Forecast units over the horizon. */
  forecastUnits: number;
  /** stockUnits / forecast daily demand; null when demand is 0. */
  daysOfStock: number | null;
  leadTimeDays: number;
  /** Probability of stockout within the horizon (0..1). */
  stockoutProbability: number;
  riskLevel: AftersalesRiskLevel;
  /** Estimated lost sales in BRL if nothing is done. */
  lostSalesBrl: number;
  action: AftersalesAction;
  /** Units to order or move; 0 for monitor. */
  recommendedQty: number;
  /** For action = transfer: the dealer with surplus. null otherwise. */
  transferFrom: { dealerId: string; dealerName: string; availableUnits: number } | null;
  /** Most recent active (open | approved | in_transit) request for this dealer x part; null if none. */
  openRequest: { id: string; status: AftersalesRequestStatus; type: AftersalesRequestType } | null;
}
export interface AftersalesRiskResponse {
  meta: AftersalesMeta;
  /** Sorted by lostSalesBrl desc (ties: stockoutProbability desc, key asc). */
  rows: AftersalesRiskRow[];
  /** Rows matching the filters before `limit`. */
  total: number;
}

// ---------------------------------------------------------------- requests (Lakebase OLTP)

/** POST /api/aftersales/requests body (JSON). */
export interface CreateAftersalesRequestBody {
  dealerId: string;
  partId: string;
  type: AftersalesRequestType;
  /** Integer 1..100000. */
  quantity: number;
  /** Required when type = "transfer": source dealer, must differ from dealerId. */
  fromDealerId?: string;
  /** Screen horizon at request time (default AFTERSALES_DEFAULT_HORIZON); the server snapshots that risk row. */
  horizonDays?: AftersalesHorizon;
  /** Optional free text, trimmed, max 500 chars. */
  note?: string;
}

export interface AftersalesRequest {
  /** UUID. */
  id: string;
  dealerId: string;
  dealerName: string;
  partId: string;
  partName: string;
  type: AftersalesRequestType;
  quantity: number;
  fromDealerId: string | null;
  note: string | null;
  /** Snapshot of what the screen showed when the request was made (null if unavailable). */
  horizonDays: AftersalesHorizon | null;
  riskLevel: AftersalesRiskLevel | null;
  lostSalesBrl: number | null;
  /** forecast_date of the risk row shown. */
  forecastDate: string | null;
  status: AftersalesRequestStatus;
  /** ISO timestamps (UTC). */
  createdAt: string;
  updatedAt: string;
  /** Constant caller kind, no PII: "app" when deployed, "local-dev" locally. */
  requestedBy: string;
}

/**
 * POST => 201 `AftersalesRequestResponse` (Location: /api/aftersales/requests/:id).
 * 409 `duplicate_request` when an active (open | approved | in_transit) request for the same dealer x part x type already exists
 * (the existing id is NOT leaked beyond `message`; the UI should show the existing request via /risk `openRequest`).
 */
export interface AftersalesRequestResponse {
  request: AftersalesRequest;
}
export interface AftersalesRequestListResponse {
  requests: AftersalesRequest[];
}
export interface AftersalesRequestListQuery {
  status?: AftersalesRequestStatus;
  dealer?: string;
  /** 1..100, default 20. */
  limit?: number;
}

// ---------------------------------------------------------------- errors

export type AftersalesErrorCode =
  | 'invalid_parameter'
  | 'not_found'
  | 'duplicate_request'
  | 'warehouse_unavailable'
  | 'lakebase_unavailable'
  | 'internal_error';

export interface AftersalesErrorBody {
  error: {
    code: AftersalesErrorCode;
    /** Short, sanitized pt-BR message (4xx) or generic English text (5xx). Safe to display. */
    message: string;
    /** Name of the offending query param / body field for invalid_parameter. */
    param?: string;
  };
}
