import { describe, expect, it } from 'vitest';
import { writeErrorCopy } from '@/api/aftersales';
import { effectiveAction } from './labels';

describe('effectiveAction', () => {
  it('keeps a transfer that has a donor dealer', () => {
    expect(effectiveAction({ action: 'transfer', transferFrom: { dealerId: 'D1' } })).toBe('transfer');
  });
  it('falls back to reorder when the transfer has no donor', () => {
    expect(effectiveAction({ action: 'transfer', transferFrom: null })).toBe('reorder');
  });
  it('leaves reorder and monitor untouched', () => {
    expect(effectiveAction({ action: 'reorder', transferFrom: null })).toBe('reorder');
    expect(effectiveAction({ action: 'monitor', transferFrom: null })).toBe('monitor');
  });
});

describe('writeErrorCopy', () => {
  it('never says "carregar" for a failed write', () => {
    for (const [status, code] of [
      [400, 'invalid_parameter'],
      [404, 'not_found'],
      [500, 'internal_error'],
      [0, undefined],
    ] as const)
      expect(writeErrorCopy(status, code)).toMatch(/^Não foi possível registrar o pedido/);
  });
  it('explains a duplicate and an unavailable service', () => {
    expect(writeErrorCopy(409, 'duplicate_request')).toMatch(/em andamento/);
    expect(writeErrorCopy(503, 'lakebase_unavailable')).toMatch(/indisponível/);
  });
});
