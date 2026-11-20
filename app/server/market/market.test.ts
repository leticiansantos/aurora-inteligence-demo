import { describe, expect, it, vi } from 'vitest';
import { TtlCache } from './cache.js';
import { ParamError, parseMarketQuery } from './params.js';
import { handleMarket } from './routes.js';
import { MarketService, buildBrandList, periodStart, shiftMonth, type RowRunner } from './service.js';

const opts = { month: true, limit: { default: 10, max: 25 } };

describe('parseMarketQuery', () => {
  it('applies defaults', () => {
    expect(parseMarketQuery({}, opts)).toEqual({
      segment: 'total',
      period: '24m',
      view: 'with_aurora',
      month: null,
      limit: 10,
    });
  });

  it('normalizes month to the first day', () => {
    expect(parseMarketQuery({ month: '2023-03' }, opts).month).toBe('2023-03-01');
    expect(parseMarketQuery({ month: '2023-03-01' }, opts).month).toBe('2023-03-01');
  });

  it.each([
    [{ segment: 'AUTOMOVEIS' }, 'segment'],
    [{ segment: ['a', 'b'] }, 'segment'],
    [{ view: '' }, 'view'],
    [{ period: '6m' }, 'period'],
    [{ limit: '0' }, 'limit'],
    [{ limit: '26' }, 'limit'],
    [{ limit: '1.5' }, 'limit'],
    [{ limit: 'abc' }, 'limit'],
    [{ month: '2023-13' }, 'month'],
    [{ month: '2023-03-15' }, 'month'],
  ])('rejects %j', (raw, param) => {
    try {
      parseMarketQuery(raw, opts);
      expect.unreachable();
    } catch (err) {
      expect(err).toBeInstanceOf(ParamError);
      expect((err as ParamError).param).toBe(param);
    }
  });

  it('ignores month and limit where the endpoint does not take them', () => {
    const q = parseMarketQuery({ month: 'garbage', limit: 'x' }, { month: false, limit: null });
    expect(q.month).toBeNull();
    expect(q.limit).toBeNull();
  });
});

describe('month helpers', () => {
  it('shifts across years', () => {
    expect(shiftMonth('2026-01-01', -1)).toBe('2025-12-01');
    expect(shiftMonth('2026-09-01', -12)).toBe('2025-09-01');
    expect(shiftMonth('2003-03-01', -3)).toBe('2002-12-01');
  });
  it('clamps the period start to the first month', () => {
    expect(periodStart('12m', '2026-09-01', '2003-01-01')).toBe('2025-10-01');
    expect(periodStart('60m', '2004-01-01', '2003-01-01')).toBe('2003-01-01');
    expect(periodStart('all', '2026-09-01', '2003-01-01')).toBe('2003-01-01');
  });
});

describe('buildBrandList', () => {
  const aggs = [
    { brand: 'A', units: 50, isAurora: false, isResidual: false },
    { brand: 'B', units: 30, isAurora: false, isResidual: false },
    { brand: 'C', units: 30, isAurora: false, isResidual: false },
    { brand: 'D', units: 10, isAurora: false, isResidual: false },
    { brand: 'AURORA MOTORS', units: 20, isAurora: true, isResidual: false },
    { brand: 'OUTRAS (NAO PUBLICADAS)', units: 10, isAurora: false, isResidual: true },
  ];

  it('uses dense ranks, keeps the residual last and reconciles totals', () => {
    const list = buildBrandList(aggs, 'with_aurora', 3, '2026-09-01', '2026-09-01');
    expect(list.totalUnits).toBe(150);
    expect(list.rows.map((r) => [r.brand, r.rank])).toEqual([
      ['A', 1],
      ['B', 2],
      ['C', 2],
      ['OUTRAS (NAO PUBLICADAS)', null],
    ]);
    expect(list.othersUnits).toBe(30);
    expect(list.rows.reduce((s, r) => s + r.units, 0) + list.othersUnits).toBe(list.totalUnits);
    expect(list.rows[list.rows.length - 1]?.label).toBe('Outras (não publicadas)');
  });

  it('drops Aurora in the real view and changes the denominator', () => {
    const list = buildBrandList(aggs, 'real', 10, '2026-09-01', '2026-09-01');
    expect(list.totalUnits).toBe(130);
    expect(list.rows.some((r) => r.isAurora)).toBe(false);
  });

  it('handles a preview month with only the residual', () => {
    const list = buildBrandList(
      [{ brand: 'OUTRAS (NAO PUBLICADAS)', units: 100, isAurora: false, isResidual: true }],
      'with_aurora',
      10,
      '2004-01-01',
      '2004-01-01'
    );
    expect(list.rows).toHaveLength(1);
    expect(list.rows[0]?.share).toBe(1);
  });
});

function fakeRunner(): { run: RowRunner; calls: string[] } {
  const calls: string[] = [];
  const run: RowRunner = (statement, params) => {
    calls.push(statement.slice(0, 40));
    if (statement.includes('first_month')) {
      return Promise.resolve([{ first_month: '2003-01-01', last_month: '2026-09-01', months_count: '285' }]);
    }
    if (statement.includes('real_totals')) {
      const rows = [
        { month: '2025-09-01', real_units: '1000', aurora_units: '30' },
        { month: '2026-09-01', real_units: '1100', aurora_units: '44' },
      ].filter((r) => r.month >= String(params.from_month) && r.month <= String(params.to_month));
      return Promise.resolve(rows);
    }
    if (statement.includes('GROUP BY brand, is_synthetic')) {
      return Promise.resolve([
        { brand: 'A', is_synthetic: 'false', is_residual: 'false', units: '700' },
        { brand: 'AURORA MOTORS', is_synthetic: 'true', is_residual: 'false', units: '44' },
        { brand: 'OUTRAS (NAO PUBLICADAS)', is_synthetic: 'false', is_residual: 'true', units: '400' },
      ]);
    }
    return Promise.resolve([]);
  };
  return { run, calls };
}

const base = { segment: 'automoveis', period: '24m', view: 'with_aurora', month: null, limit: 10 } as const;

describe('MarketService', () => {
  it('builds the summary with YoY on the view basis and the Aurora rank', async () => {
    const { run } = fakeRunner();
    const svc = new MarketService(run, { catalog: 'c', schema: 's' });
    const res = await svc.summary({ ...base });
    expect(res.month).toBe('2026-09-01');
    expect(res.market).toMatchObject({ realUnits: 1100, auroraUnits: 44, totalUnits: 1144, previousYearUnits: 1030 });
    expect(res.market.yoyPct).toBeCloseTo(1144 / 1030 - 1, 12);
    expect(res.aurora).toMatchObject({ units: 44, rank: 2, rankedBrands: 2 });
    expect(res.aurora?.share).toBeCloseTo(44 / 1144, 12);
  });

  it('keeps the real total and drops Aurora in the real view or comerciais_leves', async () => {
    const svc = new MarketService(fakeRunner().run, { catalog: 'c', schema: 's' });
    const real = await svc.summary({ ...base, view: 'real' });
    expect(real.market.realUnits).toBe(1100);
    expect(real.market.totalUnits).toBe(1100);
    expect(real.aurora).toBeNull();
    const cl = await svc.summary({ ...base, segment: 'comerciais_leves' });
    expect(cl.aurora).toBeNull();
    expect(cl.market.auroraUnits).toBeNull();
  });

  it('rejects a month outside the coverage with a ParamError', async () => {
    const svc = new MarketService(fakeRunner().run, { catalog: 'c', schema: 's' });
    await expect(svc.summary({ ...base, month: '1999-01-01' })).rejects.toBeInstanceOf(ParamError);
  });

  it('reports models as unavailable when there is no model table', async () => {
    const svc = new MarketService(fakeRunner().run, { catalog: 'c', schema: 's' });
    const res = await svc.models({ ...base });
    expect(res.available).toBe(false);
    expect(res.rows).toEqual([]);
  });

  it('serves repeated queries from the cache', async () => {
    const { run, calls } = fakeRunner();
    const svc = new MarketService(run, { catalog: 'c', schema: 's' });
    const first = await svc.timeseries({ ...base });
    const n = calls.length;
    const second = await svc.timeseries({ ...base });
    expect(calls.length).toBe(n);
    expect(first.meta.cached).toBe(false);
    expect(second.meta.cached).toBe(true);
  });
});

describe('handleMarket', () => {
  it('maps validation errors to 400 with the param name', async () => {
    const svc = new MarketService(fakeRunner().run, { catalog: 'c', schema: 's' });
    const res = await handleMarket('summary', { segment: 'x' }, svc);
    expect(res.status).toBe(400);
    expect(res.body).toMatchObject({ error: { code: 'invalid_parameter', param: 'segment' } });
  });

  it('maps warehouse failures to 503 without leaking details', async () => {
    const log = vi.fn();
    const failing: RowRunner = () => Promise.reject(new Error('token dapi123 at https://host/secret'));
    const svc = new MarketService(failing, { catalog: 'c', schema: 's' });
    const res = await handleMarket('summary', {}, svc, log);
    expect(res.status).toBe(503);
    expect(JSON.stringify(res.body)).not.toMatch(/dapi|secret|host/);
    expect(JSON.stringify(log.mock.calls)).not.toMatch(/dapi|secret/);
  });

  it('maps a code bug (non-warehouse error) to 500, not 503', async () => {
    const svc = new MarketService(fakeRunner().run, { catalog: 'c', schema: 's' });
    vi.spyOn(svc, 'summary').mockRejectedValue(new TypeError('boom'));
    const log = vi.fn();
    const res = await handleMarket('summary', {}, svc, log);
    expect(res.status).toBe(500);
    expect(res.body).toMatchObject({ error: { code: 'internal_error' } });
    expect(JSON.stringify(res.body)).not.toMatch(/boom/);
  });

  it('maps unexpected warehouse data to 500', async () => {
    const odd: RowRunner = () => Promise.resolve([{ first_month: null, last_month: null }]);
    const svc = new MarketService(odd, { catalog: 'c', schema: 's' });
    const res = await handleMarket('summary', {}, svc);
    expect(res.status).toBe(500);
  });
});

describe('TtlCache', () => {
  it('expires entries, dedupes concurrent loads and never caches failures', async () => {
    let t = 0;
    const cache = new TtlCache(1000, () => t);
    const load = vi.fn(() => Promise.resolve(1));
    const [a, b] = await Promise.all([cache.get('k', load), cache.get('k', load)]);
    expect(load).toHaveBeenCalledTimes(1);
    expect([a.cached, b.cached]).toEqual([false, true]);
    t = 2000;
    await cache.get('k', load);
    expect(load).toHaveBeenCalledTimes(2);
    await expect(cache.get('bad', () => Promise.reject(new Error('x')))).rejects.toThrow('x');
    const ok = vi.fn(() => Promise.resolve(2));
    await cache.get('bad', ok);
    expect(ok).toHaveBeenCalledTimes(1);
  });
});

describe('TtlCache eviction', () => {
  it('evicts only the oldest entry when full, keeping the rest and in-flight loads', async () => {
    const cache = new TtlCache(1000, () => 0, 3);
    const loadA = vi.fn(() => Promise.resolve('a'));
    const loadB = vi.fn(() => Promise.resolve('b'));
    await cache.get('a', loadA);
    await cache.get('b', loadB);
    let release: (v: string) => void = () => undefined;
    const slow = cache.get('slow', () => new Promise<string>((r) => (release = r)));
    await cache.get('c', () => Promise.resolve('c')); // full: evicts 'a' only
    await cache.get('b', loadB);
    expect(loadB).toHaveBeenCalledTimes(1);
    await cache.get('a', loadA);
    expect(loadA).toHaveBeenCalledTimes(2);
    release('slow');
    expect((await slow).value).toBe('slow');
  });

  it('drops expired entries before evicting live ones', async () => {
    let t = 0;
    const cache = new TtlCache(100, () => t, 2);
    await cache.get('old', () => Promise.resolve(1));
    t = 50;
    const live = vi.fn(() => Promise.resolve(2));
    await cache.get('live', live);
    t = 120; // 'old' expired, 'live' still valid
    await cache.get('new', () => Promise.resolve(3));
    await cache.get('live', live);
    expect(live).toHaveBeenCalledTimes(1);
  });
});
