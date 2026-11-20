import type {
  MarketBrandList,
  MarketBrandRow,
  MarketBrandsResponse,
  MarketLimitQuery,
  MarketModelsResponse,
  MarketQuery,
  MarketSummaryResponse,
  MarketTimeseriesPoint,
  MarketTimeseriesResponse,
} from '../../../shared/market';

/**
 * Typed mock data for the Market screen (contract: app/shared/market.ts). Synthetic placeholder names only.
 * Force a state with `?mock=loading|error|empty` in the page URL.
 */

const FIRST = '2003-01-01';
const LAST = '2026-09-01';
const AURORA_FROM = '2019-01-01';
const RESIDUAL = 'OUTRAS (NAO PUBLICADAS)';

const monthIndex = (iso: string) => Number(iso.slice(0, 4)) * 12 + Number(iso.slice(5, 7)) - 1;
const isoOf = (idx: number) => `${Math.floor(idx / 12)}-${String((idx % 12) + 1).padStart(2, '0')}-01`;
const delay = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => (clearTimeout(t), reject(new DOMException('aborted', 'AbortError'))));
  });

async function gate(signal?: AbortSignal) {
  const mode = new URLSearchParams(window.location.search).get('mock');
  await delay(mode === 'loading' ? 60_000 : 350, signal);
  if (mode === 'error') throw Object.assign(new Error('Warehouse indisponível (mock)'), { status: 503 });
}
const isEmpty = () => new URLSearchParams(window.location.search).get('mock') === 'empty';

const segFactor = (q: MarketQuery) => (q.segment === 'comerciais_leves' ? 0.22 : q.segment === 'automoveis' ? 0.8 : 1);
const hasAurora = (q: MarketQuery) => q.view !== 'real' && q.segment !== 'comerciais_leves';

function realUnitsAt(idx: number, q: MarketQuery) {
  const season = 1 + 0.08 * Math.sin(((idx % 12) / 12) * 2 * Math.PI);
  const trend = 160_000 + 1_400 * (idx - monthIndex(FIRST)) * (idx > monthIndex('2015-01-01') ? 0.45 : 1);
  return Math.round(trend * season * segFactor(q));
}
function auroraShareAt(idx: number) {
  if (idx < monthIndex(AURORA_FROM)) return null;
  const t = Math.min(1, (idx - monthIndex(AURORA_FROM)) / 48);
  return 0.012 + 0.024 * t + 0.003 * Math.sin(idx / 3);
}

function point(idx: number, q: MarketQuery): MarketTimeseriesPoint {
  const realUnits = realUnitsAt(idx, q);
  const share = hasAurora(q) ? auroraShareAt(idx) : null;
  const auroraUnits = share === null ? null : Math.round((share * realUnits) / (1 - share));
  return {
    month: isoOf(idx),
    realUnits,
    auroraUnits,
    totalUnits: realUnits + (auroraUnits ?? 0),
    auroraShare: auroraUnits === null ? null : auroraUnits / (realUnits + auroraUnits),
  };
}

const refIdx = (q: MarketQuery) => (q.month ? monthIndex(`${q.month.slice(0, 7)}-01`) : monthIndex(LAST));
const applied = (q: MarketQuery) =>
  ({
    segment: q.segment ?? 'total',
    period: q.period ?? '24m',
    view: q.view ?? 'with_aurora',
    month: isoOf(refIdx(q)),
  }) as const;

const monthsOf = (p: MarketQuery['period']) =>
  p === '12m' ? 12 : p === '60m' ? 60 : p === 'all' ? monthIndex(LAST) - monthIndex(FIRST) + 1 : 24;

export const mockMarket = {
  async summary(q: MarketQuery, signal?: AbortSignal): Promise<MarketSummaryResponse> {
    await gate(signal);
    const last = refIdx(q);
    const cur = point(last, q);
    const prev = point(last - 12, q);
    const aurora = cur.auroraUnits !== null && cur.auroraShare !== null;
    const prevShare = prev.auroraShare;
    return {
      meta: { query: applied(q), generatedAt: new Date().toISOString(), cached: false },
      month: isoOf(last),
      previousYearMonth: isoOf(last - 12),
      coverage: { firstMonth: FIRST, lastMonth: LAST, monthsCount: 285 },
      market: {
        realUnits: cur.realUnits,
        auroraUnits: cur.auroraUnits,
        totalUnits: cur.totalUnits,
        previousYearUnits: prev.totalUnits,
        yoyPct: cur.totalUnits / prev.totalUnits - 1,
      },
      aurora: aurora
        ? {
            units: cur.auroraUnits!,
            share: cur.auroraShare!,
            rank: 5,
            rankedBrands: 21,
            previousYearShare: prevShare,
            shareChangePp: prevShare === null ? null : cur.auroraShare! - prevShare,
          }
        : null,
    };
  },

  async timeseries(q: MarketQuery, signal?: AbortSignal): Promise<MarketTimeseriesResponse> {
    await gate(signal);
    const n = isEmpty() ? 0 : monthsOf(q.period);
    const last = monthIndex(LAST);
    const points = Array.from({ length: n }, (_, i) => point(last - n + 1 + i, q));
    return {
      meta: { query: applied(q), generatedAt: new Date().toISOString(), cached: false },
      from: points[0]?.month ?? LAST,
      to: LAST,
      points,
    };
  },

  async brands(q: MarketLimitQuery, signal?: AbortSignal): Promise<MarketBrandsResponse> {
    await gate(signal);
    const limit = q.limit ?? 10;
    const ref = isoOf(refIdx(q));
    const list = (scale: number, from: string): MarketBrandList => {
      const total = Math.round(realUnitsAt(refIdx(q), q) * scale);
      const names = Array.from({ length: 20 }, (_, i) => `MARCA ${String.fromCharCode(65 + i)}`);
      const weights = names.map((_, i) => 1 / (i + 1.6));
      const withAurora = hasAurora(q);
      if (withAurora) {
        names.splice(6, 0, 'AURORA MOTORS');
        weights.splice(6, 0, 0.034 * 6);
      }
      const wsum = weights.reduce((a, b) => a + b, 0) / 0.82; // top brands cover ~82%
      const all = names
        .map((brand, i) => ({ brand, units: Math.round((weights[i] / wsum) * total) }))
        .sort((a, b) => b.units - a.units);
      const top = all.slice(0, limit);
      const cut = all.slice(limit);
      const used = all.reduce((a, r) => a + r.units, 0);
      const rows: MarketBrandRow[] = top.map((r, i) => ({
        rank: i + 1,
        brand: r.brand,
        label: r.brand === 'AURORA MOTORS' ? 'Aurora Motors' : r.brand,
        units: r.units,
        share: r.units / total,
        isAurora: r.brand === 'AURORA MOTORS',
        isResidual: false,
      }));
      rows.push({
        rank: null,
        brand: RESIDUAL,
        label: 'Outras (não publicadas)',
        units: total - used,
        share: (total - used) / total,
        isAurora: false,
        isResidual: true,
      });
      return { from, to: ref, totalUnits: total, rows, othersUnits: cut.reduce((a, r) => a + r.units, 0) };
    };
    return {
      meta: { query: applied(q), generatedAt: new Date().toISOString(), cached: false },
      latestMonth: isEmpty() ? { from: ref, to: ref, totalUnits: 0, rows: [], othersUnits: 0 } : list(1, ref),
      period: isEmpty()
        ? { from: ref, to: ref, totalUnits: 0, rows: [], othersUnits: 0 }
        : list(monthsOf(q.period), isoOf(refIdx(q) - monthsOf(q.period) + 1)),
    };
  },

  async models(q: MarketLimitQuery, signal?: AbortSignal): Promise<MarketModelsResponse> {
    await gate(signal);
    const limit = q.limit ?? 10;
    const total = realUnitsAt(refIdx(q), q);
    const withAurora = hasAurora(q);
    const base = Array.from({ length: 12 }, (_, i) => ({
      brand: `MARCA ${String.fromCharCode(65 + (i % 8))}`,
      model: `MODELO ${i + 1}`,
      units: Math.round((total * 0.045) / (1 + i * 0.28)),
      isAurora: false,
    }));
    if (withAurora)
      base.push({ brand: 'AURORA MOTORS', model: 'IPE', units: Math.round(total * 0.016), isAurora: true });
    const rows = base
      .sort((a, b) => b.units - a.units)
      .slice(0, limit)
      .map((r, i) => ({ ...r, rank: i + 1, share: r.units / total }));
    const unavailable = isEmpty();
    return {
      meta: { query: applied(q), generatedAt: new Date().toISOString(), cached: false },
      month: isoOf(refIdx(q) - (refIdx(q) === monthIndex(LAST) ? 1 : 0)),
      latestMonth: isoOf(refIdx(q)),
      available: !unavailable,
      coveredUnits: Math.round(total * 0.55),
      totalUnits: total,
      rows: unavailable ? [] : rows,
    };
  },
};
