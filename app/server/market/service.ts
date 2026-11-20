import type {
  MarketAppliedQuery,
  MarketBrandList,
  MarketBrandRow,
  MarketBrandsResponse,
  MarketMeta,
  MarketModelRow,
  MarketModelsResponse,
  MarketSummaryResponse,
  MarketTimeseriesResponse,
  MarketPeriod,
  MarketView,
} from '../../shared/market.js';
import { TtlCache } from './cache.js';
import { ParamError, normalizeMonth, type ParsedMarketQuery } from './params.js';
import { brandsSql, coverageSql, marketTables, modelsSql, seriesSql, type MarketTables } from './queries.js';

export const RESIDUAL_BRAND = 'OUTRAS (NAO PUBLICADAS)';
export const RESIDUAL_LABEL = 'Outras (não publicadas)';
export const AURORA_LABEL = 'Aurora Motors';

/** Runs one parameterized statement and returns its rows (injected so tests need no warehouse). */
export type RowRunner = (
  statement: string,
  params: Record<string, string | number>
) => Promise<Record<string, unknown>[]>;

export interface Coverage {
  firstMonth: string;
  lastMonth: string;
  monthsCount: number;
}

interface SeriesRow {
  month: string;
  realUnits: number;
  auroraUnits: number | null;
}
interface BrandAgg {
  brand: string;
  isAurora: boolean;
  isResidual: boolean;
  units: number;
}

const PERIOD_MONTHS: Record<Exclude<MarketPeriod, 'all'>, number> = { '12m': 12, '24m': 24, '60m': 60 };

/** The warehouse call itself failed (outage, permission, timeout). `cause` is the original error. */
export class WarehouseError extends Error {
  constructor(readonly cause: unknown) {
    super('warehouse call failed');
    this.name = 'WarehouseError';
  }
}

/** The warehouse answered but the data is not what the contract needs (not a warehouse outage). */
export class DataShapeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'DataShapeError';
  }
}

function num(value: unknown): number {
  const n = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(n)) throw new DataShapeError('unexpected non-numeric value from warehouse');
  return n;
}
function numOrNull(value: unknown): number | null {
  return value === null || value === undefined ? null : num(value);
}
function str(value: unknown): string {
  if (typeof value !== 'string') throw new DataShapeError('unexpected non-string value from warehouse');
  return value;
}
function bool(value: unknown): boolean {
  return value === true || value === 'true';
}

/** Shifts a "YYYY-MM-01" month by `delta` months. */
export function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split('-').map(Number) as [number, number];
  const index = y * 12 + (m - 1) + delta;
  const year = Math.floor(index / 12);
  return `${String(year).padStart(4, '0')}-${String((index % 12) + 1).padStart(2, '0')}-01`;
}

/** Start of the window of `period` ending at `end` (inclusive), never before the first month. */
export function periodStart(period: MarketPeriod, end: string, firstMonth: string): string {
  if (period === 'all') return firstMonth;
  const start = shiftMonth(end, -(PERIOD_MONTHS[period] - 1));
  return start < firstMonth ? firstMonth : start;
}

function ratio(part: number, whole: number): number {
  return whole > 0 ? part / whole : 0;
}

/** Dense rank by units desc over non-residual rows, ties sharing a rank. Mutates nothing. */
export function buildBrandList(
  aggs: BrandAgg[],
  view: MarketView,
  limit: number,
  from: string,
  to: string
): MarketBrandList {
  const included = aggs.filter((a) => (view === 'with_aurora' || !a.isAurora) && a.units > 0);
  const totalUnits = included.reduce((s, a) => s + a.units, 0);
  const ranked = included
    .filter((a) => !a.isResidual)
    .sort((a, b) => b.units - a.units || a.brand.localeCompare(b.brand));
  let rank = 0;
  let previous: number | null = null;
  const withRank = ranked.map((a) => {
    if (previous === null || a.units !== previous) rank += 1;
    previous = a.units;
    return { agg: a, rank };
  });
  const toRow = (a: BrandAgg, r: number | null): MarketBrandRow => ({
    rank: r,
    brand: a.brand,
    label: a.isResidual ? RESIDUAL_LABEL : a.isAurora ? AURORA_LABEL : a.brand,
    units: a.units,
    share: ratio(a.units, totalUnits),
    isAurora: a.isAurora,
    isResidual: a.isResidual,
  });
  const top = withRank.slice(0, limit);
  const rows = top.map(({ agg, rank: r }) => toRow(agg, r));
  const othersUnits = withRank.slice(limit).reduce((s, x) => s + x.agg.units, 0);
  const residual = included.find((a) => a.isResidual);
  if (residual) rows.push(toRow(residual, null));
  return { from, to, totalUnits, rows, othersUnits };
}

export class MarketService {
  private readonly tables: MarketTables;
  private readonly cache: TtlCache;
  private readonly now: () => Date;

  constructor(
    private readonly run: RowRunner,
    options: { catalog: string; schema: string; ttlMs?: number; now?: () => Date }
  ) {
    this.tables = marketTables(options.catalog, options.schema);
    this.now = options.now ?? (() => new Date());
    this.cache = new TtlCache(options.ttlMs ?? 10 * 60_000, () => this.now().getTime());
  }

  /** Cached statement execution; also reports whether every call was a cache hit. */
  private async query(
    tracker: { cached: boolean; at: number },
    name: string,
    sql: string,
    params: Record<string, string | number>
  ): Promise<Record<string, unknown>[]> {
    const { value, cached, at } = await this.cache.get(`${name}|${JSON.stringify(params)}`, () =>
      this.run(sql, params).catch((err: unknown) => {
        throw new WarehouseError(err);
      })
    );
    if (!cached) tracker.cached = false;
    tracker.at = Math.min(tracker.at, at);
    return value;
  }

  private newTracker() {
    return { cached: true, at: this.now().getTime() };
  }

  private meta(tracker: { cached: boolean; at: number }, query: MarketAppliedQuery): MarketMeta {
    return { query, generatedAt: new Date(tracker.at).toISOString(), cached: tracker.cached };
  }

  async coverage(tracker = this.newTracker()): Promise<Coverage> {
    const rows = await this.query(tracker, 'coverage', coverageSql(this.tables), {});
    const row = rows[0];
    if (!row || row.first_month == null || row.last_month == null) throw new DataShapeError('market tables are empty');
    return {
      firstMonth: str(row.first_month),
      lastMonth: str(row.last_month),
      monthsCount: num(row.months_count),
    };
  }

  /** Resolves the reference month: default latest; must exist in the coverage. */
  private resolveMonth(requested: string | null, coverage: Coverage): string {
    if (requested === null) return coverage.lastMonth;
    if (requested < coverage.firstMonth || requested > coverage.lastMonth) {
      throw new ParamError(
        'month',
        `Mês fora da cobertura dos dados (${coverage.firstMonth.slice(0, 7)} a ${coverage.lastMonth.slice(0, 7)}).`
      );
    }
    return requested;
  }

  private applied(q: ParsedMarketQuery, month: string): MarketAppliedQuery {
    return { segment: q.segment, period: q.period, view: q.view, month };
  }

  private async series(
    tracker: { cached: boolean; at: number },
    segment: string,
    from: string,
    to: string
  ): Promise<SeriesRow[]> {
    const rows = await this.query(tracker, 'series', seriesSql(this.tables), {
      segment,
      from_month: from,
      to_month: to,
    });
    return rows.map((r) => ({
      month: String(r.month),
      realUnits: num(r.real_units),
      auroraUnits: numOrNull(r.aurora_units),
    }));
  }

  private async brandAggs(
    tracker: { cached: boolean; at: number },
    segment: string,
    from: string,
    to: string
  ): Promise<BrandAgg[]> {
    const rows = await this.query(tracker, 'brands', brandsSql(this.tables), {
      segment,
      from_month: from,
      to_month: to,
    });
    return rows.map((r) => ({
      brand: String(r.brand),
      isAurora: bool(r.is_synthetic),
      isResidual: bool(r.is_residual),
      units: num(r.units),
    }));
  }

  /** Aurora applies to automoveis only and only in the with_aurora view. */
  private static auroraApplies(q: ParsedMarketQuery): boolean {
    return q.view === 'with_aurora' && q.segment !== 'comerciais_leves';
  }

  async timeseries(q: ParsedMarketQuery): Promise<MarketTimeseriesResponse> {
    const tracker = this.newTracker();
    const coverage = await this.coverage(tracker);
    const to = coverage.lastMonth;
    const from = periodStart(q.period, to, coverage.firstMonth);
    const rows = await this.series(tracker, q.segment, from, to);
    const withAurora = MarketService.auroraApplies(q);
    const points = rows.map((r) => {
      const aurora = withAurora ? r.auroraUnits : null;
      const totalUnits = r.realUnits + (aurora ?? 0);
      return {
        month: r.month,
        realUnits: r.realUnits,
        auroraUnits: aurora,
        totalUnits,
        auroraShare: aurora === null ? null : ratio(aurora, totalUnits),
      };
    });
    return {
      meta: this.meta(tracker, this.applied(q, to)),
      from: points[0]?.month ?? from,
      to: points[points.length - 1]?.month ?? to,
      points,
    };
  }

  async brands(q: ParsedMarketQuery): Promise<MarketBrandsResponse> {
    const tracker = this.newTracker();
    const coverage = await this.coverage(tracker);
    const month = this.resolveMonth(q.month, coverage);
    const from = periodStart(q.period, month, coverage.firstMonth);
    const limit = q.limit ?? 10;
    const [latest, period] = await Promise.all([
      this.brandAggs(tracker, q.segment, month, month),
      this.brandAggs(tracker, q.segment, from, month),
    ]);
    return {
      meta: this.meta(tracker, this.applied(q, month)),
      latestMonth: buildBrandList(latest, q.view, limit, month, month),
      period: buildBrandList(period, q.view, limit, from, month),
    };
  }

  async models(q: ParsedMarketQuery): Promise<MarketModelsResponse> {
    const tracker = this.newTracker();
    const coverage = await this.coverage(tracker);
    const requested = this.resolveMonth(q.month, coverage);
    const limit = q.limit ?? 10;
    const rows = await this.query(tracker, 'models', modelsSql(this.tables), {
      segment: q.segment,
      month: requested,
    });
    const shownMonth = rows.length > 0 ? String(rows[0]?.month) : requested;
    const [totalRow] = await this.series(tracker, q.segment, shownMonth, shownMonth);
    const aurora = MarketService.auroraApplies(q) ? (totalRow?.auroraUnits ?? 0) : 0;
    const totalUnits = (totalRow?.realUnits ?? 0) + aurora;
    const models = rows
      .map((r) => ({
        brand: String(r.brand),
        model: String(r.model),
        isAurora: bool(r.is_synthetic),
        units: num(r.units),
      }))
      .filter((m) => (q.view === 'with_aurora' || !m.isAurora) && m.units > 0)
      .sort((a, b) => b.units - a.units || a.brand.localeCompare(b.brand) || a.model.localeCompare(b.model));
    const out: MarketModelRow[] = models.slice(0, limit).map((m, i) => ({
      rank: i + 1,
      brand: m.brand,
      model: m.model,
      units: m.units,
      share: ratio(m.units, totalUnits),
      isAurora: m.isAurora,
    }));
    return {
      meta: this.meta(tracker, this.applied(q, requested)),
      month: shownMonth,
      latestMonth: requested,
      available: models.length > 0,
      coveredUnits: models.reduce((s, m) => s + m.units, 0),
      totalUnits,
      rows: out,
    };
  }

  async summary(q: ParsedMarketQuery): Promise<MarketSummaryResponse> {
    const tracker = this.newTracker();
    const coverage = await this.coverage(tracker);
    const month = this.resolveMonth(q.month, coverage);
    const previousYearMonth = shiftMonth(month, -12);
    const [rows, aggs] = await Promise.all([
      this.series(tracker, q.segment, previousYearMonth, month),
      this.brandAggs(tracker, q.segment, month, month),
    ]);
    const withAurora = MarketService.auroraApplies(q);
    const totals = (r: SeriesRow | undefined) =>
      r === undefined ? null : { real: r.realUnits, aurora: withAurora ? r.auroraUnits : null };
    const cur = totals(rows.find((r) => r.month === month));
    if (!cur) throw new DataShapeError('no market total for the reference month');
    const prev = totals(rows.find((r) => r.month === previousYearMonth));
    const sum = (t: { real: number; aurora: number | null }) => t.real + (t.aurora ?? 0);
    const totalUnits = sum(cur);
    const previousYearUnits = prev ? sum(prev) : null;

    let aurora: MarketSummaryResponse['aurora'] = null;
    if (withAurora && cur.aurora !== null && cur.aurora > 0) {
      const list = buildBrandList(aggs, q.view, Number.MAX_SAFE_INTEGER, month, month);
      const row = list.rows.find((r) => r.isAurora);
      const prevShare = prev && prev.aurora !== null ? ratio(prev.aurora, sum(prev)) : null;
      const share = ratio(cur.aurora, totalUnits);
      aurora = {
        units: cur.aurora,
        share,
        rank: row?.rank ?? null,
        rankedBrands: list.rows.filter((r) => !r.isResidual).length,
        previousYearShare: prevShare,
        shareChangePp: prevShare === null ? null : share - prevShare,
      };
    }
    return {
      meta: this.meta(tracker, this.applied(q, month)),
      month,
      previousYearMonth,
      coverage: { firstMonth: coverage.firstMonth, lastMonth: coverage.lastMonth, monthsCount: coverage.monthsCount },
      market: {
        realUnits: cur.real,
        auroraUnits: cur.aurora,
        totalUnits,
        previousYearUnits,
        yoyPct: previousYearUnits ? totalUnits / previousYearUnits - 1 : null,
      },
      aurora,
    };
  }
}

export { normalizeMonth };
