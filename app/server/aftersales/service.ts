import {
  AFTERSALES_ACTIONS,
  AFTERSALES_DEFAULT_HORIZON,
  AFTERSALES_HORIZONS,
  AFTERSALES_RISK_LEVELS,
  type AftersalesAction,
  type AftersalesFiltersResponse,
  type AftersalesForecastResponse,
  type AftersalesHorizon,
  type AftersalesMeta,
  type AftersalesRequestStatus,
  type AftersalesRequestType,
  type AftersalesRiskLevel,
  type AftersalesRiskResponse,
  type AftersalesRiskRow,
  type AftersalesSummaryResponse,
} from '../../shared/aftersales.js';
import { invalid } from './errors.js';
import { text } from './util.js';
import { SYNCED_SCHEMA, type Catalog, type Queryable, type RequestRepository, type RiskSnapshot } from './requests.js';

const S = SYNCED_SCHEMA;
const num = (v: unknown): number => Number(v);
const numOrNull = (v: unknown): number | null => (v === null || v === undefined ? null : Number(v));
const day = (v: unknown): string => (v instanceof Date ? v.toISOString().slice(0, 10) : text(v).slice(0, 10));

export interface ParsedFilters {
  dealer: string | null;
  category: string | null;
  horizon: AftersalesHorizon;
}

const single = (raw: Record<string, unknown>, name: string): string | undefined => {
  const v = raw[name];
  if (v === undefined) return undefined;
  if (typeof v !== 'string') throw invalid(name, `Parâmetro "${name}" deve ser informado uma única vez.`);
  if (v.length === 0) throw invalid(name, `Parâmetro "${name}" não pode ser vazio.`);
  return v;
};

/** Validates dealer/category against the loaded options ("all" = no filter) and the horizon. */
export function parseFilters(
  raw: Record<string, unknown>,
  options: { dealers: Set<string>; categories: Set<string> }
): ParsedFilters {
  const pick = (name: 'dealer' | 'category', allowed: Set<string>): string | null => {
    const v = single(raw, name);
    if (v === undefined || v === 'all') return null;
    if (!allowed.has(v)) throw invalid(name, `Valor inválido para "${name}".`);
    return v;
  };
  const h = single(raw, 'horizon');
  let horizon: AftersalesHorizon = AFTERSALES_DEFAULT_HORIZON;
  if (h !== undefined) {
    const n = /^(0|[1-9]\d*)$/.test(h) ? Number(h) : NaN;
    if (!(AFTERSALES_HORIZONS as readonly number[]).includes(n)) {
      throw invalid('horizon', `Valor inválido para "horizon". Use um de: ${AFTERSALES_HORIZONS.join(', ')}.`);
    }
    horizon = n as AftersalesHorizon;
  }
  return { dealer: pick('dealer', options.dealers), category: pick('category', options.categories), horizon };
}

export function parseRiskExtras(raw: Record<string, unknown>): { minLevel: AftersalesRiskLevel; limit: number } {
  const lvl = single(raw, 'minLevel') ?? 'low';
  if (!(AFTERSALES_RISK_LEVELS as readonly string[]).includes(lvl)) {
    throw invalid('minLevel', `Valor inválido para "minLevel". Use um de: ${AFTERSALES_RISK_LEVELS.join(', ')}.`);
  }
  const l = single(raw, 'limit');
  let limit = 50;
  if (l !== undefined) {
    if (!/^(0|[1-9]\d*)$/.test(l) || Number(l) < 1 || Number(l) > 200) {
      throw invalid('limit', 'Parâmetro "limit" deve ser um inteiro entre 1 e 200.');
    }
    limit = Number(l);
  }
  return { minLevel: lvl as AftersalesRiskLevel, limit };
}

/** Levels at or above `min`, most severe first in AFTERSALES_RISK_LEVELS. */
export const levelsFrom = (min: AftersalesRiskLevel): AftersalesRiskLevel[] =>
  AFTERSALES_RISK_LEVELS.slice(0, AFTERSALES_RISK_LEVELS.indexOf(min) + 1);

export class AftersalesService implements Catalog {
  private options: { dealers: Set<string>; categories: Set<string> } | null = null;
  private optionsLoadedAt = 0;

  constructor(
    private readonly db: Queryable,
    private readonly requests: RequestRepository,
    private readonly log: (message: string) => void = (m) => console.warn(m),
    /** Filter options come from the synced tables, which refresh after each scoring run. */
    private readonly optionsTtlMs = 5 * 60_000,
    private readonly now: () => number = Date.now
  ) {}

  // ---- Catalog (used to validate POST /requests)
  async dealerExists(id: string): Promise<boolean> {
    const { rows } = await this.db.query(`SELECT 1 FROM ${S}.aftersales_lb_dealers WHERE dealer_id = $1`, [id]);
    return rows.length > 0;
  }
  async partExists(id: string): Promise<boolean> {
    const { rows } = await this.db.query(`SELECT 1 FROM ${S}.aftersales_lb_parts WHERE part_id = $1`, [id]);
    return rows.length > 0;
  }
  async riskSnapshot(dealerId: string, partId: string, horizon: AftersalesHorizon): Promise<RiskSnapshot | null> {
    const { rows } = await this.db.query(
      `SELECT stock_units, risk_level, lost_sales_brl, forecast_date FROM ${S}.aftersales_lb_stockout_risk
       WHERE dealer_id = $1 AND part_id = $2 AND horizon_days = $3`,
      [dealerId, partId, horizon]
    );
    if (rows.length === 0) return null;
    const r = rows[0];
    return {
      stockUnits: num(r.stock_units),
      riskLevel: r.risk_level as AftersalesRiskLevel,
      lostSalesBrl: num(r.lost_sales_brl),
      forecastDate: day(r.forecast_date),
    };
  }

  // ---- filters / options
  async loadOptions() {
    const dealers = (
      await this.db.query(
        `SELECT dealer_id, dealer_name, city, state FROM ${S}.aftersales_lb_dealers ORDER BY dealer_id`
      )
    ).rows;
    const categories = (
      await this.db.query(
        `SELECT DISTINCT category_id, category_name FROM ${S}.aftersales_lb_parts ORDER BY category_name`
      )
    ).rows;
    this.optionsLoadedAt = this.now();
    this.options = {
      dealers: new Set(dealers.map((d) => text(d.dealer_id))),
      categories: new Set(categories.map((c) => text(c.category_id))),
    };
    return { dealers, categories };
  }

  async parse(raw: Record<string, unknown>): Promise<ParsedFilters> {
    if (!this.options || this.now() - this.optionsLoadedAt > this.optionsTtlMs) await this.loadOptions();
    return parseFilters(raw, this.options!);
  }

  private async meta(f: ParsedFilters): Promise<AftersalesMeta> {
    const { rows } = await this.db.query(
      `SELECT (SELECT max(forecast_date) FROM ${S}.aftersales_lb_stockout_risk) AS forecast_date,
              (SELECT max(week_start) FROM ${S}.aftersales_lb_forecast_weekly WHERE NOT is_future) AS last_week,
              (SELECT model_version FROM ${S}.aftersales_lb_model_metrics WHERE is_champion
                 ORDER BY logged_at DESC LIMIT 1) AS model_version,
              (SELECT max(scored_at) FROM ${S}.aftersales_lb_stockout_risk) AS synced_at`
    );
    const r = rows[0] ?? {};
    const lastWeek = r.last_week ? new Date(`${day(r.last_week)}T00:00:00Z`) : null;
    if (lastWeek) lastWeek.setUTCDate(lastWeek.getUTCDate() + 6);
    return {
      query: { dealer: f.dealer, category: f.category, horizon: f.horizon },
      forecastDate: r.forecast_date ? day(r.forecast_date) : '',
      dataThrough: lastWeek ? lastWeek.toISOString().slice(0, 10) : '',
      modelVersion: r.model_version ? `aftersales_demand_forecaster@champion v${text(r.model_version)}` : 'unknown',
      syncedAt: r.synced_at ? new Date(r.synced_at as string).toISOString() : null,
      synthetic: true,
    };
  }

  async filters(): Promise<AftersalesFiltersResponse> {
    const { dealers, categories } = await this.loadOptions();
    const { query: _query, ...meta } = await this.meta({
      dealer: null,
      category: null,
      horizon: AFTERSALES_DEFAULT_HORIZON,
    });
    return {
      dealers: dealers.map((d) => ({
        id: text(d.dealer_id),
        name: text(d.dealer_name),
        city: text(d.city),
        state: text(d.state),
      })),
      categories: categories.map((c) => ({ id: text(c.category_id), name: text(c.category_name) })),
      horizons: AFTERSALES_HORIZONS,
      defaultHorizon: AFTERSALES_DEFAULT_HORIZON,
      meta,
    };
  }

  async summary(f: ParsedFilters): Promise<AftersalesSummaryResponse> {
    const risk = await this.db.query(
      `SELECT r.risk_level, count(*) AS n,
              coalesce(sum(r.lost_sales_brl) FILTER (WHERE r.action <> 'monitor'), 0) AS avoided,
              coalesce(sum(r.stock_units), 0) AS stock, coalesce(sum(r.forecast_units), 0) AS forecast
       FROM ${S}.aftersales_lb_stockout_risk r JOIN ${S}.aftersales_lb_parts p ON p.part_id = r.part_id
       WHERE r.horizon_days = $3 AND ($1::text IS NULL OR r.dealer_id = $1) AND ($2::text IS NULL OR p.category_id = $2)
       GROUP BY r.risk_level`,
      [f.dealer, f.category, f.horizon]
    );
    const dist = Object.fromEntries(AFTERSALES_RISK_LEVELS.map((l) => [l, 0])) as Record<AftersalesRiskLevel, number>;
    let avoided = 0,
      stock = 0,
      forecast = 0;
    for (const r of risk.rows) {
      dist[r.risk_level as AftersalesRiskLevel] = num(r.n);
      avoided += num(r.avoided);
      stock += num(r.stock);
      forecast += num(r.forecast);
    }
    const fill = await this.db.query(
      `SELECT sum(f.sold_units) AS sold, sum(f.actual_units) AS demand
       FROM ${S}.aftersales_lb_forecast_weekly f JOIN ${S}.aftersales_lb_parts p ON p.part_id = f.part_id
       WHERE NOT f.is_future
         AND f.week_start > (SELECT max(week_start) FROM ${S}.aftersales_lb_forecast_weekly WHERE NOT is_future) - 28
         AND ($1::text IS NULL OR f.dealer_id = $1) AND ($2::text IS NULL OR p.category_id = $2)`,
      [f.dealer, f.category]
    );
    const demand = num(fill.rows[0]?.demand ?? 0);
    return {
      meta: await this.meta(f),
      kpis: {
        partsAtRisk: { value: dist.critical + dist.high, previous: null },
        lostSalesAvoidedBrl: { value: avoided, previous: null },
        fillRate: { value: demand > 0 ? num(fill.rows[0].sold) / demand : null, previous: null },
        daysOfStock: { value: forecast > 0 ? stock / (forecast / f.horizon) : null, previous: null },
      },
      riskDistribution: dist,
    };
  }

  async forecast(f: ParsedFilters, partId: string | null): Promise<AftersalesForecastResponse> {
    if (partId !== null && !(await this.partExists(partId))) throw invalid('partId', 'Peça desconhecida.');
    const where = `($1::text IS NULL OR f.dealer_id = $1) AND ($2::text IS NULL OR p.category_id = $2)
                   AND ($3::text IS NULL OR f.part_id = $3)`;
    const params = [f.dealer, f.category, partId];
    const series = await this.db.query(
      `SELECT f.week_start, bool_or(f.is_future) AS is_future, sum(f.actual_units) AS actual,
              sum(f.forecast_units) AS forecast, sum(f.lower_units) AS lower, sum(f.upper_units) AS upper
       FROM ${S}.aftersales_lb_forecast_weekly f JOIN ${S}.aftersales_lb_parts p ON p.part_id = f.part_id
       WHERE ${where} GROUP BY f.week_start ORDER BY f.week_start`,
      params
    );
    const acc = await this.db.query(
      `SELECT sum(abs(f.actual_units - f.forecast_units)) AS err, sum(abs(f.actual_units - f.baseline_units)) AS base_err,
              sum(f.actual_units) AS actual
       FROM ${S}.aftersales_lb_forecast_weekly f JOIN ${S}.aftersales_lb_parts p ON p.part_id = f.part_id
       WHERE NOT f.is_future AND f.forecast_units IS NOT NULL AND ${where}`,
      params
    );
    const a = acc.rows[0];
    const actual = num(a?.actual ?? 0);
    return {
      meta: await this.meta(f),
      series: series.rows.map((r) => ({
        weekStart: day(r.week_start),
        actualUnits: numOrNull(r.actual),
        forecastUnits: numOrNull(r.forecast),
        lowerUnits: numOrNull(r.lower),
        upperUnits: numOrNull(r.upper),
        isFuture: Boolean(r.is_future),
      })),
      accuracy: actual > 0 ? { wape: num(a.err) / actual, baselineWape: num(a.base_err) / actual } : null,
    };
  }

  async risk(
    f: ParsedFilters,
    extras: { minLevel: AftersalesRiskLevel; limit: number }
  ): Promise<AftersalesRiskResponse> {
    const { rows } = await this.db.query(
      `SELECT r.dealer_id, d.dealer_name, r.part_id, p.part_name, p.category_id, p.category_name,
              r.stock_units, r.on_order_units, r.forecast_units, r.days_of_stock, r.lead_time_days, r.stockout_probability,
              r.risk_level, r.lost_sales_brl, r.action, r.recommended_qty, r.transfer_from_dealer_id,
              td.dealer_name AS transfer_from_name, r.transfer_from_excess_units, count(*) OVER () AS total
       FROM ${S}.aftersales_lb_stockout_risk r
       JOIN ${S}.aftersales_lb_parts p ON p.part_id = r.part_id
       JOIN ${S}.aftersales_lb_dealers d ON d.dealer_id = r.dealer_id
       LEFT JOIN ${S}.aftersales_lb_dealers td ON td.dealer_id = r.transfer_from_dealer_id
       WHERE r.horizon_days = $3 AND ($1::text IS NULL OR r.dealer_id = $1) AND ($2::text IS NULL OR p.category_id = $2)
         AND r.risk_level = ANY($4::text[])
       ORDER BY r.lost_sales_brl DESC, r.stockout_probability DESC, r.dealer_id, r.part_id LIMIT $5`,
      [f.dealer, f.category, f.horizon, levelsFrom(extras.minLevel), extras.limit]
    );
    // The ranking must not depend on the OLTP side: if open requests cannot be read (table not migrated yet,
    // permission, blip), degrade to "no open requests" instead of failing the whole screen.
    const active = await this.requests
      .activeByKey(rows.map((r) => ({ dealerId: text(r.dealer_id), partId: text(r.part_id) })))
      .catch((err: unknown) => {
        this.log(`aftersales: open requests unavailable, degrading: ${err instanceof Error ? err.name : 'error'}`);
        return new Map<string, { id: string; status: AftersalesRequestStatus; type: AftersalesRequestType }>();
      });
    const out: AftersalesRiskRow[] = rows.map((r) => {
      const key = `${text(r.dealer_id)}:${text(r.part_id)}`;
      const action = r.action as AftersalesAction;
      if (!(AFTERSALES_ACTIONS as readonly string[]).includes(action))
        throw new Error(`unexpected action ${String(action)}`);
      return {
        key,
        dealerId: text(r.dealer_id),
        dealerName: text(r.dealer_name),
        partId: text(r.part_id),
        partName: text(r.part_name),
        categoryId: text(r.category_id),
        categoryName: text(r.category_name),
        stockUnits: num(r.stock_units),
        onOrderUnits: num(r.on_order_units),
        forecastUnits: num(r.forecast_units),
        daysOfStock: numOrNull(r.days_of_stock),
        leadTimeDays: num(r.lead_time_days),
        stockoutProbability: num(r.stockout_probability),
        riskLevel: r.risk_level as AftersalesRiskLevel,
        lostSalesBrl: num(r.lost_sales_brl),
        action,
        recommendedQty: num(r.recommended_qty),
        transferFrom: r.transfer_from_dealer_id
          ? {
              dealerId: text(r.transfer_from_dealer_id),
              dealerName: text(r.transfer_from_name),
              availableUnits: num(r.transfer_from_excess_units),
            }
          : null,
        openRequest: active.get(key) ?? null,
      };
    });
    return { meta: await this.meta(f), rows: out, total: rows.length ? num(rows[0].total) : 0 };
  }
}
