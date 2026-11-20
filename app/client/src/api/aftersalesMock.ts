import type {
  AftersalesAction,
  AftersalesAppliedQuery,
  AftersalesFiltersResponse,
  AftersalesForecastPoint,
  AftersalesForecastQuery,
  AftersalesForecastResponse,
  AftersalesMeta,
  AftersalesQuery,
  AftersalesRequest,
  AftersalesRequestListQuery,
  AftersalesRequestListResponse,
  AftersalesRequestResponse,
  AftersalesRiskLevel,
  AftersalesRiskQuery,
  AftersalesRiskResponse,
  AftersalesRiskRow,
  AftersalesSummaryResponse,
  CreateAftersalesRequestBody,
} from '../../../shared/aftersales';

/**
 * Typed mock data for the Pós-venda screen (contract: app/shared/aftersales.ts). 100% synthetic, generic part names.
 * Force a state with `?mock=loading|error|empty|duplicate` in the page URL.
 */

const FORECAST_DATE = '2026-09-28';
const DATA_THROUGH = '2026-09-27';

const DEALERS = [
  { id: 'D001', name: 'Aurora São Paulo Centro', city: 'São Paulo', state: 'SP' },
  { id: 'D002', name: 'Aurora Campinas', city: 'Campinas', state: 'SP' },
  { id: 'D003', name: 'Aurora Belo Horizonte', city: 'Belo Horizonte', state: 'MG' },
  { id: 'D004', name: 'Aurora Curitiba', city: 'Curitiba', state: 'PR' },
  { id: 'D005', name: 'Aurora Recife', city: 'Recife', state: 'PE' },
];
const CATEGORIES = [
  { id: 'brakes', name: 'Freios' },
  { id: 'filters', name: 'Filtros' },
  { id: 'suspension', name: 'Suspensão' },
  { id: 'electrical', name: 'Elétrica' },
  { id: 'engine', name: 'Motor' },
];
const PARTS = [
  { id: 'P101', name: 'Pastilha de freio dianteira', cat: 'brakes', price: 180 },
  { id: 'P102', name: 'Disco de freio traseiro', cat: 'brakes', price: 320 },
  { id: 'P201', name: 'Filtro de óleo', cat: 'filters', price: 45 },
  { id: 'P202', name: 'Filtro de ar do motor', cat: 'filters', price: 70 },
  { id: 'P301', name: 'Amortecedor dianteiro', cat: 'suspension', price: 540 },
  { id: 'P302', name: 'Bieleta da barra estabilizadora', cat: 'suspension', price: 95 },
  { id: 'P401', name: 'Bateria 60 Ah', cat: 'electrical', price: 480 },
  { id: 'P402', name: 'Vela de ignição', cat: 'electrical', price: 38 },
  { id: 'P501', name: 'Correia dentada', cat: 'engine', price: 210 },
  { id: 'P502', name: 'Bomba d’água', cat: 'engine', price: 360 },
];

const delay = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => (clearTimeout(t), reject(new DOMException('aborted', 'AbortError'))));
  });
const mode = () => new URLSearchParams(window.location.search).get('mock');
async function gate(signal?: AbortSignal) {
  await delay(mode() === 'loading' ? 60_000 : 350, signal);
  if (mode() === 'error') throw Object.assign(new Error('Lakebase indisponível (mock)'), { status: 503 });
}

// Small deterministic hash so rows are stable between renders.
const h = (s: string) => [...s].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7);

const applied = (q: AftersalesQuery): AftersalesAppliedQuery => ({
  dealer: q.dealer && q.dealer !== 'all' ? q.dealer : null,
  category: q.category && q.category !== 'all' ? q.category : null,
  horizon: q.horizon ?? 28,
});
const meta = (q: AftersalesQuery): AftersalesMeta => ({
  query: applied(q),
  forecastDate: FORECAST_DATE,
  dataThrough: DATA_THROUGH,
  modelVersion: 'aftersales_forecast@champion v3 (mock)',
  syncedAt: '2026-09-28T06:15:00Z',
  synthetic: true,
});

const requests: AftersalesRequest[] = [];
const openByKey = () =>
  new Map(requests.filter((r) => r.status === 'open').map((r) => [`${r.dealerId}:${r.partId}`, r]));

function baseRows(q: AftersalesQuery): AftersalesRiskRow[] {
  const a = applied(q);
  const open = openByKey();
  const rows: AftersalesRiskRow[] = [];
  for (const d of DEALERS) {
    if (a.dealer && a.dealer !== d.id) continue;
    for (const p of PARTS) {
      if (a.category && a.category !== p.cat) continue;
      const seed = h(`${d.id}${p.id}`);
      const daily = 1 + (seed % 9) * 0.7;
      const forecastUnits = Math.round(daily * a.horizon);
      const leadTimeDays = 4 + (seed % 11);
      const stockUnits = Math.round(daily * (1 + ((seed >>> 3) % 31)));
      const daysOfStock = stockUnits / daily;
      const gap = daysOfStock - Math.max(leadTimeDays, a.horizon / 2);
      const prob = Math.min(0.99, Math.max(0.02, 0.5 - gap / 20));
      const level: AftersalesRiskLevel = prob > 0.8 ? 'critical' : prob > 0.55 ? 'high' : prob > 0.3 ? 'medium' : 'low';
      const missing = Math.max(0, forecastUnits + Math.round(daily * leadTimeDays) - stockUnits);
      const surplusDealer = DEALERS[(seed >>> 5) % DEALERS.length];
      const canTransfer = level !== 'low' && surplusDealer.id !== d.id && (seed >>> 7) % 3 !== 0;
      const action: AftersalesAction = level === 'low' ? 'monitor' : canTransfer ? 'transfer' : 'reorder';
      const r = open.get(`${d.id}:${p.id}`);
      rows.push({
        key: `${d.id}:${p.id}`,
        dealerId: d.id,
        dealerName: d.name,
        partId: p.id,
        partName: p.name,
        categoryId: p.cat,
        categoryName: CATEGORIES.find((c) => c.id === p.cat)!.name,
        stockUnits,
        onOrderUnits: seed % 4 === 0 ? Math.round(daily * 7) : 0,
        forecastUnits,
        daysOfStock: Math.round(daysOfStock * 10) / 10,
        leadTimeDays,
        stockoutProbability: Math.round(prob * 100) / 100,
        riskLevel: level,
        lostSalesBrl: Math.round(missing * p.price * prob),
        action,
        recommendedQty: action === 'monitor' ? 0 : Math.max(1, missing),
        transferFrom:
          action === 'transfer'
            ? { dealerId: surplusDealer.id, dealerName: surplusDealer.name, availableUnits: Math.max(1, missing) + 6 }
            : null,
        openRequest: r ? { id: r.id, status: r.status, type: r.type } : null,
      });
    }
  }
  return rows.sort((x, y) => y.lostSalesBrl - x.lostSalesBrl || y.stockoutProbability - x.stockoutProbability);
}

export const mockAftersales = {
  async filters(signal?: AbortSignal): Promise<AftersalesFiltersResponse> {
    await gate(signal);
    const { query: _q, ...m } = meta({});
    return { dealers: DEALERS, categories: CATEGORIES, horizons: [14, 28, 56], defaultHorizon: 28, meta: m };
  },

  async summary(q: AftersalesQuery, signal?: AbortSignal): Promise<AftersalesSummaryResponse> {
    await gate(signal);
    const rows = mode() === 'empty' ? [] : baseRows(q);
    const dist: Record<AftersalesRiskLevel, number> = { critical: 0, high: 0, medium: 0, low: 0 };
    rows.forEach((r) => dist[r.riskLevel]++);
    const atRisk = dist.critical + dist.high;
    const stock = rows.reduce((a, r) => a + r.stockUnits, 0);
    const demand = rows.reduce((a, r) => a + r.forecastUnits / applied(q).horizon, 0);
    return {
      meta: meta(q),
      kpis: {
        partsAtRisk: { value: atRisk, previous: Math.round(atRisk * 1.15) },
        lostSalesAvoidedBrl: {
          value: rows.filter((r) => r.action !== 'monitor').reduce((a, r) => a + r.lostSalesBrl, 0),
          previous: null,
        },
        fillRate: { value: rows.length ? 0.912 : 0, previous: 0.897 },
        daysOfStock: { value: demand ? Math.round((stock / demand) * 10) / 10 : 0, previous: 17.4 },
      },
      riskDistribution: dist,
    };
  },

  async forecast(q: AftersalesForecastQuery, signal?: AbortSignal): Promise<AftersalesForecastResponse> {
    await gate(signal);
    if (mode() === 'empty') return { meta: meta(q), series: [], accuracy: null };
    const scale = (q.dealer && q.dealer !== 'all' ? 1 : DEALERS.length) * (q.category && q.category !== 'all' ? 1 : 3);
    const start = Date.parse(`${FORECAST_DATE}T00:00:00Z`) - 26 * 7 * 86_400_000;
    const series: AftersalesForecastPoint[] = Array.from({ length: 26 + 8 }, (_, i) => {
      const t = start + i * 7 * 86_400_000;
      const weekStart = new Date(t).toISOString().slice(0, 10);
      const isFuture = weekStart >= FORECAST_DATE;
      const base = scale * (60 + 12 * Math.sin(i / 3.2));
      const forecast = Math.round(base * (1 + 0.03 * Math.cos(i)));
      return {
        weekStart,
        actualUnits: isFuture ? null : Math.round(base * (1 + 0.1 * Math.sin(i * 1.7))),
        forecastUnits: i < 13 ? null : forecast,
        lowerUnits: i < 13 ? null : Math.round(forecast * 0.86),
        upperUnits: i < 13 ? null : Math.round(forecast * 1.14),
        isFuture,
      };
    });
    return { meta: meta(q), series, accuracy: { wape: 0.138, baselineWape: 0.211 } };
  },

  async risk(q: AftersalesRiskQuery, signal?: AbortSignal): Promise<AftersalesRiskResponse> {
    await gate(signal);
    if (mode() === 'empty') return { meta: meta(q), rows: [], total: 0 };
    const order: AftersalesRiskLevel[] = ['low', 'medium', 'high', 'critical'];
    const min = order.indexOf(q.minLevel ?? 'low');
    const all = baseRows(q).filter((r) => order.indexOf(r.riskLevel) >= min);
    return { meta: meta(q), rows: all.slice(0, q.limit ?? 50), total: all.length };
  },

  async requests(q: AftersalesRequestListQuery, signal?: AbortSignal): Promise<AftersalesRequestListResponse> {
    await gate(signal);
    const list = requests
      .filter((r) => (!q.status || r.status === q.status) && (!q.dealer || r.dealerId === q.dealer))
      .slice(0, q.limit ?? 20);
    return { requests: list };
  },

  async createRequest(body: CreateAftersalesRequestBody, signal?: AbortSignal): Promise<AftersalesRequestResponse> {
    await delay(500, signal);
    if (mode() === 'error') throw Object.assign(new Error('Lakebase indisponível (mock)'), { status: 503 });
    if (mode() === 'duplicate' || openByKey().has(`${body.dealerId}:${body.partId}`))
      throw Object.assign(new Error('Pedido duplicado (mock)'), { status: 409, code: 'duplicate_request' });
    const row = baseRows({ horizon: body.horizonDays }).find((r) => r.key === `${body.dealerId}:${body.partId}`);
    const now = new Date().toISOString();
    const dealer = DEALERS.find((d) => d.id === body.dealerId)!;
    const part = PARTS.find((p) => p.id === body.partId)!;
    const request: AftersalesRequest = {
      id: crypto.randomUUID(),
      dealerId: body.dealerId,
      dealerName: dealer.name,
      partId: body.partId,
      partName: part.name,
      type: body.type,
      quantity: body.quantity,
      fromDealerId: body.fromDealerId ?? null,
      note: body.note?.trim() || null,
      status: 'open',
      createdAt: now,
      updatedAt: now,
      horizonDays: body.horizonDays ?? 28,
      riskLevel: row?.riskLevel ?? null,
      lostSalesBrl: row?.lostSalesBrl ?? null,
      forecastDate: FORECAST_DATE,
      requestedBy: 'local-dev',
    };
    requests.unshift(request);
    return { request };
  },
};
