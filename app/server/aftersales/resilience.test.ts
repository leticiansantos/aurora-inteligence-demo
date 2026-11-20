/* eslint-disable @typescript-eslint/require-await -- async fakes mirror the real async interfaces */
import type { Application } from 'express';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from './errors.js';
import { RequestRepository } from './requests.js';
import { mapError, registerAftersalesUnavailable } from './routes.js';
import { AftersalesService } from './service.js';
import { isTransientConnectionError, withConnectionRetry } from './util.js';

describe('transient connection errors', () => {
  it.each([
    [new Error('timeout exceeded when trying to connect'), true],
    [new Error('Connection terminated unexpectedly'), true],
    [Object.assign(new Error('x'), { code: '57P01' }), true],
    [Object.assign(new Error('x'), { code: 'ECONNREFUSED' }), true],
    [Object.assign(new Error('dup'), { code: '23505' }), false],
    [new Error('syntax error'), false],
    ['nope', false],
  ])('%j => %s', (err, expected) => {
    expect(isTransientConnectionError(err)).toBe(expected);
  });

  it('maps code-less cold-start errors to 503 and unknown ones to 500', () => {
    const log = vi.fn();
    expect(mapError(new Error('Connection terminated unexpectedly'), log).status).toBe(503);
    expect(mapError(new Error('timeout exceeded when trying to connect'), log).status).toBe(503);
    expect(mapError(new Error('boom'), log).status).toBe(500);
    expect(mapError(new ApiError(404, 'not_found', 'x'), log).status).toBe(404);
  });

  it('retries exactly once on a transient error, never on others', async () => {
    let calls = 0;
    const db = withConnectionRetry(
      {
        query: async () => {
          calls += 1;
          if (calls === 1) throw new Error('timeout exceeded when trying to connect');
          return { rows: [{ ok: 1 }] };
        },
      },
      0,
      async () => undefined
    );
    await expect(db.query('select 1')).resolves.toEqual({ rows: [{ ok: 1 }] });
    expect(calls).toBe(2);

    let n = 0;
    const always = withConnectionRetry(
      {
        query: async () => {
          n += 1;
          throw new Error('Connection terminated unexpectedly');
        },
      },
      0,
      async () => undefined
    );
    await expect(always.query('select 1')).rejects.toThrow('terminated');
    expect(n).toBe(2);

    let m = 0;
    const logical = withConnectionRetry(
      {
        query: async () => {
          m += 1;
          throw Object.assign(new Error('dup'), { code: '23505' });
        },
      },
      0,
      async () => undefined
    );
    await expect(logical.query('insert')).rejects.toThrow('dup');
    expect(m).toBe(1);
  });
});

describe('AftersalesService', () => {
  const riskRow = {
    dealer_id: 'D001',
    dealer_name: 'Loja',
    part_id: 'P001',
    part_name: 'Peça',
    category_id: 'brakes',
    category_name: 'Freios',
    stock_units: 1,
    on_order_units: 0,
    forecast_units: 10,
    days_of_stock: 1,
    lead_time_days: 7,
    stockout_probability: 0.9,
    risk_level: 'critical',
    lost_sales_brl: 100,
    action: 'reorder',
    recommended_qty: 9,
    transfer_from_dealer_id: null,
    transfer_from_name: null,
    transfer_from_excess_units: null,
    total: 1,
  };
  const db = (counter?: { options: number }) => ({
    query: async (text: string) => {
      if (text.includes('stockout_risk r')) return { rows: [riskRow] };
      if (text.includes('model_metrics'))
        return { rows: [{ forecast_date: '2026-11-16', last_week: '2026-11-09', model_version: '1' }] };
      if (text.includes('DISTINCT category_id')) return { rows: [{ category_id: 'brakes', category_name: 'Freios' }] };
      if (text.includes('SELECT dealer_id, dealer_name')) {
        if (counter) counter.options += 1;
        return { rows: [{ dealer_id: 'D001', dealer_name: 'Loja', city: 'X', state: 'SP' }] };
      }
      return { rows: [] };
    },
  });

  it('/risk degrades to no open requests when the OLTP side fails (no DDL dependency)', async () => {
    const requests = new RequestRepository({
      query: async () => {
        throw Object.assign(new Error('relation does not exist'), { code: '42P01' });
      },
    });
    const log = vi.fn();
    const service = new AftersalesService(db(), requests, log);
    const out = await service.risk({ dealer: null, category: null, horizon: 28 }, { minLevel: 'low', limit: 10 });
    expect(out.rows).toHaveLength(1);
    expect(out.rows[0].openRequest).toBeNull();
    expect(log).toHaveBeenCalled();
  });

  it('reloads filter options after the TTL', async () => {
    let t = 0;
    const counter = { options: 0 };
    const requests = new RequestRepository({ query: async () => ({ rows: [] }) });
    const service = new AftersalesService(
      db(counter),
      requests,
      () => undefined,
      1000,
      () => t
    );
    await service.parse({});
    await service.parse({});
    expect(counter.options).toBe(1);
    t = 1001;
    await service.parse({});
    expect(counter.options).toBe(2);
  });
});

describe('registerAftersalesUnavailable', () => {
  it('answers 503 lakebase_unavailable', () => {
    let handler: ((req: unknown, res: unknown) => void) | undefined;
    const app = { use: (_p: string, h: typeof handler) => (handler = h) } as unknown as Application;
    registerAftersalesUnavailable(app);
    const res = { setHeader: vi.fn(), status: vi.fn().mockReturnThis(), json: vi.fn() };
    handler?.({}, res);
    expect(res.status).toHaveBeenCalledWith(503);
    const body = res.json.mock.calls[0][0] as { error: { code: string } };
    expect(body.error.code).toBe('lakebase_unavailable');
  });
});
