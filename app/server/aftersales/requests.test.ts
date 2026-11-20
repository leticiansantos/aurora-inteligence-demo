/* eslint-disable @typescript-eslint/require-await -- async fakes mirror the real async interfaces */
import { describe, expect, it } from 'vitest';
import { ApiError } from './errors.js';
import {
  RequestRepository,
  parseCreateBody,
  parseListQuery,
  parseRequestId,
  validateAgainstCatalog,
  type Catalog,
} from './requests.js';

const ok = { dealerId: 'D001', partId: 'P001', type: 'reorder', quantity: 5 };
const paramOf = (fn: () => unknown): string | undefined => {
  try {
    fn();
  } catch (e) {
    expect(e).toBeInstanceOf(ApiError);
    return (e as ApiError).param;
  }
  return 'NO_ERROR';
};

describe('parseCreateBody', () => {
  it('accepts a minimal reorder', () => {
    expect(parseCreateBody(ok)).toMatchObject({ ...ok, note: undefined });
  });
  it.each([
    [{ ...ok, quantity: 0 }, 'quantity'],
    [{ ...ok, quantity: -1 }, 'quantity'],
    [{ ...ok, quantity: 1.5 }, 'quantity'],
    [{ ...ok, quantity: '5' }, 'quantity'],
    [{ ...ok, quantity: 100001 }, 'quantity'],
    [{ ...ok, quantity: null }, 'quantity'],
    [{ ...ok, extra: 1 }, 'extra'],
    [{ ...ok, note: 'x'.repeat(501) }, 'note'],
    [{ ...ok, note: 'a\u0000b' }, 'note'],
    [{ ...ok, fromDealerId: 'D002' }, 'fromDealerId'],
    [{ ...ok, type: 'transfer' }, 'fromDealerId'],
    [{ ...ok, type: 'transfer', fromDealerId: 'D001' }, 'fromDealerId'],
    [{ ...ok, type: 'swap' }, 'type'],
    [{ ...ok, horizonDays: 7 }, 'horizonDays'],
    [{ ...ok, dealerId: '' }, 'dealerId'],
    ['text', 'body'],
    [[], 'body'],
    [null, 'body'],
  ])('rejects %j', (raw, param) => {
    expect(paramOf(() => parseCreateBody(raw))).toBe(param);
  });
  it('accepts 1e3, emoji; blank note becomes undefined', () => {
    expect(parseCreateBody({ ...ok, quantity: 1e3, note: '   ' }).note).toBeUndefined();
    expect(parseCreateBody({ ...ok, note: ' urgente 🚗 ' }).note).toBe('urgente 🚗');
  });
});

describe('validateAgainstCatalog', () => {
  const snap = (stockUnits: number) => ({
    stockUnits,
    riskLevel: 'high' as const,
    lostSalesBrl: 10,
    forecastDate: '2026-11-16',
  });
  const stock: Record<string, number> = { 'D001:P001': 2, 'D002:P001': 10 };
  const catalog: Catalog = {
    dealerExists: async (d) => ['D001', 'D002'].includes(d),
    partExists: async (p) => p === 'P001',
    riskSnapshot: async (d, p) => (stock[`${d}:${p}`] === undefined ? null : snap(stock[`${d}:${p}`])),
  };
  it('rejects unknown dealer/part and uncarried part', async () => {
    await expect(validateAgainstCatalog({ ...ok, dealerId: 'X' } as never, catalog)).rejects.toMatchObject({
      param: 'dealerId',
    });
    await expect(validateAgainstCatalog({ ...ok, partId: 'X' } as never, catalog)).rejects.toMatchObject({
      param: 'partId',
    });
    await expect(
      validateAgainstCatalog({ ...ok, dealerId: 'D001', partId: 'P001' } as never, {
        ...catalog,
        riskSnapshot: async () => null,
      })
    ).rejects.toMatchObject({ param: 'partId' });
  });
  it('snapshots risk and defaults the horizon', async () => {
    await expect(validateAgainstCatalog(ok as never, catalog)).resolves.toMatchObject({
      horizonDays: 28,
      snapshot: { riskLevel: 'high' },
    });
  });
  it('rejects a transfer whose donor does not carry the part', async () => {
    const t = { dealerId: 'D001', partId: 'P001', type: 'transfer', fromDealerId: 'D002', quantity: 1 } as const;
    const noDonor: Catalog = { ...catalog, riskSnapshot: async (d) => (d === 'D001' ? snap(5) : null) };
    await expect(validateAgainstCatalog(t, noDonor)).rejects.toMatchObject({ param: 'fromDealerId' });
  });
  it('checks donor availability for transfers', async () => {
    const t = { dealerId: 'D001', partId: 'P001', type: 'transfer', fromDealerId: 'D002' } as const;
    await expect(validateAgainstCatalog({ ...t, quantity: 11 }, catalog)).rejects.toMatchObject({ param: 'quantity' });
    await expect(validateAgainstCatalog({ ...t, quantity: 10 }, catalog)).resolves.toMatchObject({ type: 'transfer' });
  });
});

describe('ids and list query', () => {
  it('rejects non-UUID id', () => {
    expect(paramOf(() => parseRequestId('abc'))).toBe('id');
    expect(parseRequestId('123E4567-E89B-12D3-A456-426614174000')).toBe('123e4567-e89b-12d3-a456-426614174000');
  });
  it('validates list params', () => {
    expect(parseListQuery({})).toEqual({ status: undefined, dealer: undefined, limit: 20 });
    expect(paramOf(() => parseListQuery({ status: 'nope' }))).toBe('status');
    expect(paramOf(() => parseListQuery({ limit: '101' }))).toBe('limit');
    expect(paramOf(() => parseListQuery({ limit: ['1', '2'] }))).toBe('limit');
  });
});

describe('RequestRepository', () => {
  it('maps 23505 to 409 and uses parameterized SQL', async () => {
    const calls: { text: string; params?: unknown[] }[] = [];
    const repo = new RequestRepository({
      query: async (text, params) => {
        calls.push({ text, params });
        if (!text.includes('INSERT')) return { rows: [] };
        throw Object.assign(new Error('dup'), { code: '23505' });
      },
    });
    await expect(
      repo.create(
        {
          ...ok,
          type: 'reorder',
          horizonDays: 28,
          snapshot: { stockUnits: 1, riskLevel: 'high', lostSalesBrl: 1, forecastDate: '2026-11-16' },
        } as never,
        'local-dev'
      )
    ).rejects.toMatchObject({ status: 409, code: 'duplicate_request' });
    const insert = calls.find((c) => c.text.includes('INSERT'))!;
    expect(insert.text).toContain('$1');
    expect(insert.text).not.toContain('D001');
  });
  it('404 when missing', async () => {
    const repo = new RequestRepository({ query: async () => ({ rows: [] }) });
    await expect(repo.get('123e4567-e89b-12d3-a456-426614174000')).rejects.toMatchObject({ status: 404 });
  });

  it('retries the migration after a failure and runs it once after success', async () => {
    let fail = true;
    const ddl: string[] = [];
    const repo = new RequestRepository({
      query: async (text) => {
        if (fail) throw new Error('endpoint suspended');
        ddl.push(text);
        return { rows: [] };
      },
    });
    await expect(repo.init()).rejects.toThrow('suspended');
    fail = false;
    await repo.init();
    const n = ddl.length;
    await repo.init();
    expect(ddl.length).toBe(n);
  });
});
